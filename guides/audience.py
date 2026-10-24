"""Who sees which post. Every list, search, guide page, file and counter goes through here.

A post is for one of (GuidePage.audience):
- AUDIENCE_ALL: every venue's staff and manager, also of venues added later (the default),
- AUDIENCE_STAFF: the staff of the chosen venues (GuidePage.venues), and their managers,
- AUDIENCE_MANAGERS: only the managers of the chosen venues.
Staff of one venue and managers of another are never mixed in one post (user's rule, 2026-10-23).
Editors (department users, superuser) see every live post. A logged-in user that is neither
(should not exist) sees only the posts for all venues.
"""

from django.db.models import Q

from .models import AUDIENCE_ALL, AUDIENCE_MANAGERS, AUDIENCE_STAFF, GuidePage

FOR_VENUE = "За вашия обект"
MANAGERS_ONLY = "Само за управители"
FOR_SOME = "За избрани обекти"
EVERYBODY = (AUDIENCE_ALL, [])
# Lists of venue names longer than this are shown as a number ("7 обекта").
NAMES_SHOWN = 4


class AudienceError(Exception):
    """Nobody would see the post. The message is shown as is."""


def venue_q(venue, role):
    """Q for the posts that the staff (role "staff") or the manager ("manager") of a venue may see."""
    from venues.models import MANAGER

    targeted = [AUDIENCE_STAFF, AUDIENCE_MANAGERS] if role == MANAGER else [AUDIENCE_STAFF]
    for_venue = GuidePage.venues.through.objects.filter(venue=venue).values("guidepage_id")
    return Q(audience=AUDIENCE_ALL) | Q(audience__in=targeted, pk__in=for_venue)


def audience_q(user):
    """Q for the posts the user may see, or None for "all of them" (editors)."""
    from dashboard.access import is_editor
    from venues.access import reader

    if is_editor(user):
        return None
    me = reader(user)
    return venue_q(me.venue, me.role) if me else Q(audience=AUDIENCE_ALL)


def visible_guides(user, guides=None):
    """The live posts (of `guides`, default all) that the user may see."""
    guides = GuidePage.objects.live() if guides is None else guides
    q = audience_q(user)
    return guides if q is None else guides.filter(q)


def can_see(user, guide):
    return guide.live and visible_guides(user).filter(pk=guide.pk).exists()


def accounts_for(guide):
    """The venue accounts (of working venues) that may see the post: the expected „Прочетох“."""
    from venues.models import MANAGER, VenueAccount

    accounts = VenueAccount.objects.filter(venue__is_active=True, user__is_active=True).select_related("venue", "user")
    if guide.audience == AUDIENCE_ALL:
        return accounts
    accounts = accounts.filter(venue__in=guide.venues.all())
    return accounts.filter(role=MANAGER) if guide.audience == AUDIENCE_MANAGERS else accounts


def visible_media(user):
    """(image ids, document ids) of the live posts the user may see."""
    images, documents = set(), set()
    for media in visible_guides(user).values_list("uploaded_media", flat=True):
        images.update((media or {}).get("images", []))
        documents.update((media or {}).get("documents", []))
    return images, documents


def normalize(all_venues, staff_venues, manager_venues):
    """The picker's ticks („Всички обекти“, the staff column, the „Само управителят“ column) as
    stored: (audience, venues). Raises AudienceError for nothing chosen or both columns."""
    if all_venues:
        return EVERYBODY
    staff_venues, manager_venues = list(staff_venues), list(manager_venues)
    if staff_venues and manager_venues:
        raise AudienceError("Изберете или служители (с техните управители), или само управители – не двете заедно.")
    if staff_venues:
        return AUDIENCE_STAFF, staff_venues
    if manager_venues:
        return AUDIENCE_MANAGERS, manager_venues
    raise AudienceError("Изберете кой да вижда публикацията: „Всички обекти“ или поне един обект.")


def badge(user, guide):
    """The label on a post for this user: "" (for everybody), „За вашия обект“ or „Само за управители“.

    Staff never get a manager-only post, so they can never see „Само за управители“.
    """
    from dashboard.access import is_editor

    if guide.audience == AUDIENCE_ALL:
        return ""
    if guide.audience == AUDIENCE_MANAGERS:
        return MANAGERS_ONLY
    return FOR_SOME if is_editor(user) else FOR_VENUE


def _names(venues):
    names = [v.name for v in venues]
    if len(names) > NAMES_SHOWN:
        return f"{len(names)} обекта"
    return ", ".join(names)


def summary(guide):
    """Who sees the post, for editors: "Всички обекти", "Перник, Варна (служители и управител)",
    "Само управителите на Перник"."""
    if guide.audience == AUDIENCE_ALL:
        return "Всички обекти"
    venues = list(guide.venues.all())
    if not venues:
        return "Никой (обектите са изтрити)"
    if guide.audience == AUDIENCE_MANAGERS:
        return f"Само управителите на {_names(venues)}"
    return f"{_names(venues)} (служители и управител)"


def posts_only_for(venue):
    """Live or archived posts that nobody else would see if this venue were deleted."""
    posts = GuidePage.objects.exclude(audience=AUDIENCE_ALL).filter(venues=venue)
    return [p for p in posts if not p.venues.exclude(pk=venue.pk).exists()]
