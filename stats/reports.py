"""What the numbers say: most read guides (department cards) and searches (home page), and the „Статистика“ tab."""
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from search.views import matching_guides

from .models import GuideStat, SearchStat, Vote

POPULAR_DAYS = 30
# A search is shown on the public home page only after this many searches, so one-off typos stay out.
POPULAR_MIN_SEARCHES = 3


def since(days):
    return timezone.localdate() - timedelta(days=days - 1)


def most_read(guides, days=POPULAR_DAYS, limit=6):
    return (
        guides.filter(stats__day__gte=since(days))
        .annotate(recent_views=Sum("stats__views"))
        .filter(recent_views__gt=0)
        .order_by("-recent_views", "-last_published_at")[:limit]
    )


def highlights(guides, limit=3):
    """The most read guides, topped up with the newest ones (for a department's card on the home page)."""
    items = list(most_read(guides, limit=limit))
    if len(items) < limit:
        newest = guides.exclude(pk__in=[g.pk for g in items]).order_by("-last_published_at")
        items += list(newest[: limit - len(items)])
    return items


def _searches(days, venue=None, role=None):
    rows = SearchStat.objects.filter(day__gte=since(days))
    if venue is not None:
        rows = rows.filter(venue=venue)
    if role is not None:
        rows = rows.filter(role=role)
    return rows


def top_searches(days=POPULAR_DAYS, limit=8, min_count=1, venue=None, role=None):
    """The most frequent searches that found something: [{"query", "total"}]."""
    return list(
        _searches(days, venue, role).filter(results__gt=0)
        .values("query")
        .annotate(total=Sum("count"))
        .filter(total__gte=min_count)
        .order_by("-total", "query")[:limit]
    )


def popular_for(user, limit=6):
    """„Често търсено“ on the home page: the staff's frequent searches that find something for this user.

    Only staff searches, so what venue managers search for never shows on a staff PC.
    """
    from guides.audience import visible_guides
    from venues.models import STAFF

    candidates = top_searches(limit=limit * 3, min_count=POPULAR_MIN_SEARCHES, role=STAFF)
    visible = visible_guides(user)
    return [c for c in candidates if matching_guides(c["query"], visible).exists()][:limit]


def failed_searches(days=POPULAR_DAYS, limit=30, venue=None):
    """Searches that found nothing and still find nothing now: [{"query", "total", "last_day"}].

    For one venue, "still nothing" means nothing its manager (who sees the most) could find.
    """
    found = {}
    for row in _searches(days, venue):
        entry = found.setdefault(row.query, {"query": row.query, "total": 0, "last_day": None, "last_found": None})
        if row.results == 0:
            entry["total"] += row.count
            entry["last_day"] = max(entry["last_day"] or row.day, row.day)
        else:
            entry["last_found"] = max(entry["last_found"] or row.day, row.day)
    failed = [e for e in found.values() if e["total"] and (e["last_found"] is None or e["last_found"] < e["last_day"])]
    # A guide may have been published since the last search (e.g. today).
    failed = [e for e in failed if not matching_guides(e["query"], _guides_of(venue)).exists()]
    failed.sort(key=lambda e: (-e["total"], e["query"]))
    return failed[:limit]


def _guides_of(venue):
    from guides.audience import venue_q
    from guides.models import GuidePage
    from venues.models import MANAGER

    guides = GuidePage.objects.live()
    return guides if venue is None else guides.filter(venue_q(venue, MANAGER))


def guide_report(guides, days=POPULAR_DAYS, venue=None):
    """The guides with their views and votes in the period, most viewed first."""
    recent = Q(stats__day__gte=since(days))
    if venue is not None:
        recent &= Q(stats__venue=venue)
    return guides.annotate(
        recent_views=Coalesce(Sum("stats__views", filter=recent), 0),
        yes_votes=Coalesce(Sum("stats__helpful", filter=recent), 0),
        no_votes=Coalesce(Sum("stats__not_helpful", filter=recent), 0),
    ).order_by("-recent_views", "title")


def no_reasons(guides, days=POPULAR_DAYS, venue=None, limit=100):
    """What the venues wrote with „Не“ on these guides, newest first (not the training venue)."""
    votes = (
        Vote.objects.filter(helpful=False, day__gte=since(days), guide__in=guides)
        .exclude(reason="").exclude(user__venue_account__venue__is_training=True)
        .select_related("guide", "user__venue_account__venue").order_by("-day", "-pk")
    )
    if venue is not None:
        votes = votes.filter(user__venue_account__venue=venue)
    return list(votes[:limit])


def venue_report(venues, days=POPULAR_DAYS, guides=None):
    """Per venue: views, „Не“ votes, searches and searches without results in the period.

    `guides` limits views and votes to these posts (a department user's own).
    """
    stats = GuideStat.objects.filter(day__gte=since(days))
    if guides is not None:
        stats = stats.filter(guide__in=guides)
    views = {r["venue"]: r for r in stats.values("venue").annotate(views=Sum("views"), yes=Sum("helpful"), no=Sum("not_helpful"))}
    searches = {
        r["venue"]: r for r in SearchStat.objects.filter(day__gte=since(days)).values("venue")
        .annotate(total=Sum("count"), empty=Sum("count", filter=Q(results=0)), queries=Count("id"))
    }
    rows = []
    for venue in venues:
        v, s = views.get(venue.pk, {}), searches.get(venue.pk, {})
        rows.append({
            "venue": venue, "views": v.get("views") or 0, "yes": v.get("yes") or 0, "no": v.get("no") or 0,
            "searches": s.get("total") or 0, "empty": s.get("empty") or 0,
        })
    return rows
