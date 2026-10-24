"""Counting what the venues do on the site: guide views, „Помогна ли ви?“ votes and searches.

Only venue accounts (staff and venue managers) are counted, per venue; not the content managers
checking their own pages, and not the training venue. One row per guide (or search) per venue per
day keeps the tables small. No person is stored.
"""
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from search.views import QUERY_MAX_LENGTH

from .models import GuideStat, SearchStat, Vote


def is_prefetch(request):
    """The browser loading a page ahead, before anybody looks at it."""
    purpose = request.headers.get("Sec-Purpose", "") or request.headers.get("Purpose", "")
    return "prefetch" in purpose


def counted_reader(request):
    """The (venue, role) whose visit counts, else None (content managers, training, browser prefetches)."""
    from venues.access import reader

    me = reader(request.user)
    if me is None or me.venue.is_training or is_prefetch(request):
        return None
    return me


def normalize(query):
    return " ".join(query.lower().split())[:QUERY_MAX_LENGTH]


def _add(model, keys, **amounts):
    row, _ = model.objects.get_or_create(day=timezone.localdate(), **keys)
    model.objects.filter(pk=row.pk).update(**{name: F(name) + n for name, n in amounts.items()})


def count_view(guide, me):
    _add(GuideStat, {"guide": guide, "venue": me.venue}, views=1)


def count_vote(guide, helpful, me):
    _add(GuideStat, {"guide": guide, "venue": me.venue}, **{"helpful" if helpful else "not_helpful": 1})


def count_search(query, results, me):
    query = normalize(query)
    if query:
        row, _ = SearchStat.objects.get_or_create(day=timezone.localdate(), query=query, venue=me.venue, role=me.role)
        SearchStat.objects.filter(pk=row.pk).update(count=F("count") + 1, results=results)


def purge(days):
    """Delete counters older than `days` (run nightly by cleanup_media). Returns the number of rows."""
    before = timezone.localdate() - timedelta(days=days)
    return sum(model.objects.filter(day__lt=before).delete()[0] for model in (GuideStat, SearchStat, Vote))
