"""What each venue account has opened (Seen) and confirmed with „Прочетох“ (Ack).

Unlike the counters in tracking.py these are per account (an account belongs to a venue, not to a
person), because they answer "is it new for this PC?" and "did Перник read it?".
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Ack, Seen


def mark_seen(guide, user):
    Seen.objects.get_or_create(guide=guide, user=user)


def confirm(guide, user):
    Ack.objects.get_or_create(guide=guide, user=user)


def unread(user, guides):
    """Of `guides` (already filtered to what the user may see): the ones published in the last
    UNREAD_DAYS that the account hasn't opened, and every one waiting for its „Прочетох“."""
    from guides.models import UNREAD_DAYS

    since = timezone.now() - timedelta(days=UNREAD_DAYS)
    seen = Seen.objects.filter(user=user).values("guide_id")
    acked = Ack.objects.filter(user=user).values("guide_id")
    return guides.filter(
        Q(first_published_at__gte=since) & ~Q(pk__in=seen) | Q(needs_ack=True) & ~Q(pk__in=acked)
    )


def unread_ids(request):
    """The ids of unread(…) for the current user (none for anybody but a venue account), worked
    out once per request: every card on a page asks."""
    if not hasattr(request, "_infohub_unread"):
        from guides.audience import visible_guides
        from venues.access import is_reader

        ids = set()
        if is_reader(request.user):
            ids = set(unread(request.user, visible_guides(request.user)).values_list("pk", flat=True))
        request._infohub_unread = ids
    return request._infohub_unread


def report(guide):
    """Per venue account that may see the post (not the training venue): when it opened the post
    and when it confirmed it. Rows: (account, seen_at or None, acked_at or None)."""
    from guides.audience import accounts_for

    accounts = list(accounts_for(guide).exclude(venue__is_training=True))
    users = [a.user_id for a in accounts]
    seen = dict(Seen.objects.filter(guide=guide, user_id__in=users).values_list("user_id", "at"))
    acked = dict(Ack.objects.filter(guide=guide, user_id__in=users).values_list("user_id", "at"))
    return [(a, seen.get(a.user_id), acked.get(a.user_id)) for a in accounts]


def ack_counts(guides):
    """{guide id: number of „Прочетох“ of counted venue accounts} for the panel list."""
    from django.db.models import Count

    rows = (
        Ack.objects.filter(guide__in=guides, user__venue_account__venue__is_training=False)
        .values("guide_id").annotate(n=Count("id"))
    )
    return {row["guide_id"]: row["n"] for row in rows}
