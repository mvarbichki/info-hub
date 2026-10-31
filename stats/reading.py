"""What each venue account has opened (Seen) and what the venues' managers confirmed with
„Прочетох и запознах екипа“ / „Прочетох“ (Ack).

Unlike the counters in tracking.py these are per account (an account belongs to a venue, not to a
person), because they answer "is it new for this PC?" and "did Перник read it?". Only a manager
confirms: the staff account is shared by the whole venue, the manager answers for the team. One
manager's confirmation counts for the venue.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from guides.models import AUDIENCE_MANAGERS, UNREAD_DAYS
from venues.access import reader
from venues.models import MANAGER

from .models import Ack, Seen

# A confirmation counts unless it was a plain „Прочетох“ and the post now asks to brief the team.
COUNTS = Q(team=True) | Q(guide__audience=AUDIENCE_MANAGERS)


def mark_seen(guide, user):
    Seen.objects.get_or_create(guide=guide, user=user)


def confirms(user):
    """Whether the account is asked to confirm posts: a venue's manager."""
    account = reader(user)
    return account is not None and account.role == MANAGER


def confirm(guide, user):
    ack, created = Ack.objects.get_or_create(guide=guide, user=user, defaults={"team": guide.ack_briefs_team})
    if not created and guide.ack_briefs_team and not ack.team:  # read only, now asked to brief the team
        ack.team, ack.at = True, timezone.now()
        ack.save(update_fields=["team", "at"])


def _venue_acks(venue):
    """The confirmations of a venue (by any of its manager accounts)."""
    return Ack.objects.filter(COUNTS, user__venue_account__venue=venue, user__venue_account__role=MANAGER)


def venue_ack(guide, user):
    """The venue's confirmation of the post (Ack, with the user who gave it), or None."""
    return _venue_acks(reader(user).venue).filter(guide=guide).select_related("user").order_by("at").first()


def unread(user, guides):
    """Of `guides` (already filtered to what the user may see): the ones published in the last
    UNREAD_DAYS that the account hasn't opened and, for a manager, every one its venue hasn't confirmed."""
    since = timezone.now() - timedelta(days=UNREAD_DAYS)
    seen = Seen.objects.filter(user=user).values("guide_id")
    new = Q(first_published_at__gte=since) & ~Q(pk__in=seen)
    if not confirms(user):
        return guides.filter(new)
    acked = _venue_acks(reader(user).venue).values("guide_id")
    return guides.filter(new | Q(needs_ack=True) & ~Q(pk__in=acked))


def unread_ids(request):
    """The ids of unread(…) for the current user (none for anybody but a venue account), worked
    out once per request: every card on a page asks."""
    if not hasattr(request, "_infohub_unread"):
        from guides.audience import visible_guides

        ids = set()
        if reader(request.user) is not None:
            ids = set(unread(request.user, visible_guides(request.user)).values_list("pk", flat=True))
        request._infohub_unread = ids
    return request._infohub_unread


def report(guide):
    """Per venue account that may see the post (not the training venue): when it opened the post
    and, for a manager, when it confirmed it. Rows: (account, seen_at or None, acked_at or None)."""
    from guides.audience import accounts_for

    accounts = list(accounts_for(guide).exclude(venue__is_training=True))
    users = [a.user_id for a in accounts]
    seen = dict(Seen.objects.filter(guide=guide, user_id__in=users).values_list("user_id", "at"))
    managers = [a.user_id for a in accounts if a.role == MANAGER]
    acked = dict(Ack.objects.filter(COUNTS, guide=guide, user_id__in=managers).values_list("user_id", "at"))
    return [(a, seen.get(a.user_id), acked.get(a.user_id)) for a in accounts]


def venue_progress(rows):
    """From report(…) rows: (confirmed venue names, venues still to confirm, venues without a manager
    account, which can't confirm). Each a list of names in the rows' order."""
    venues = {}
    for account, _, acked in rows:
        state = venues.setdefault(account.venue.name, {"manager": False, "acked": False})
        if account.role == MANAGER:
            state["manager"] = True
            state["acked"] = state["acked"] or bool(acked)
    confirmed = [name for name, s in venues.items() if s["acked"]]
    missing = [name for name, s in venues.items() if s["manager"] and not s["acked"]]
    no_manager = [name for name, s in venues.items() if not s["manager"]]
    return confirmed, missing, no_manager


def ack_progress(guide):
    """(confirmed venues, venues that should confirm) for „Прочетох: 12 / 23“ in the panel list."""
    from guides.audience import accounts_for

    expected = set(accounts_for(guide).exclude(venue__is_training=True).filter(role=MANAGER).values_list("venue_id", flat=True))
    confirmed = set(
        Ack.objects.filter(COUNTS, guide=guide, user__venue_account__role=MANAGER, user__venue_account__venue__in=expected)
        .values_list("user__venue_account__venue_id", flat=True)
    )
    return len(confirmed), len(expected)
