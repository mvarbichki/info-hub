"""Venue accounts: who is a reader of which venue, and creating/changing venues and their accounts."""

import re
import secrets
from typing import NamedTuple

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from guides.slugs import TRANSLIT

from .models import MANAGER, STAFF, Venue, VenueAccount

# A group without permissions for every venue account, so their rights show in /admin/ → Groups.
VENUE_GROUP = "Обекти – само преглед"
TRAINING_NAME = "Обучение"
# New login names: Latin lower case, digits, _ . - (logins are not case-sensitive anyway).
USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,39}$")
# Generated passwords: no look-alikes (0/o, 1/l/i), so they can be typed from a printed sheet.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


class Reader(NamedTuple):
    venue: Venue
    role: str  # STAFF or MANAGER


def reader(user):
    """(venue, role) of a venue account, else None. Cached on the user object for the request."""
    if not getattr(user, "is_authenticated", False):
        return None
    if not hasattr(user, "_infohub_reader"):
        account = VenueAccount.objects.select_related("venue").filter(user=user).first()
        user._infohub_reader = Reader(account.venue, account.role) if account else None
    return user._infohub_reader


def is_reader(user):
    return reader(user) is not None


# Logins write „ц“ as c (Център → centar), unlike the post addresses.
LOGIN_TRANSLIT = {**TRANSLIT, ord("ц"): "c"}


def login_base(name):
    """Short Latin start of a login from the venue name, one word as the user names them:
    the place after the dash, its first word when it has several („София – Цариградско шосе“ → carigradsko,
    „София – Център“ → centar); a city of several words → initials + last word („Велико Търново“ →
    vtarnovo, „Стара Загора“ → szagora); „Перник“ → pernik."""
    parts = re.split(r"\s*[–—-]\s*", name.strip())
    words = re.findall(r"[a-z0-9]+", (parts[-1] or name).lower().translate(LOGIN_TRANSLIT))
    if not words:
        return "obekt"
    if len(parts) > 1 or len(words) == 1:
        base = words[0]
    else:
        base = "".join(word[0] for word in words[:-1]) + words[-1]
    return base[:30] if len(base) >= 2 else "obekt"


def suggest_username(venue, role, taken=None):
    """pernik_staff, or pernik_staff2, pernik_staff3… when taken (`taken`: lower-case names in use)."""
    if taken is None:
        taken = {name.lower() for name in get_user_model().objects.values_list("username", flat=True)}
    name, n = f"{login_base(venue.name)}_{role}", 2
    candidate = name
    while candidate in taken:
        candidate, n = f"{name}{n}", n + 1
    return candidate


def _venue_group():
    return Group.objects.get_or_create(name=VENUE_GROUP)[0]


@transaction.atomic
def create_account(username, venue, role, password=""):
    """A read-only login for the venue. Empty password = can't log in until one is set."""
    user = get_user_model()(username=username)
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    user.save()
    user.groups.add(_venue_group())
    VenueAccount.objects.create(user=user, venue=venue, role=role)
    return user


def new_password(user=None):
    """A random password that is easy to read and type, e.g. "k7mp-4rtx-9wqa" (about 59 bits)."""
    while True:
        password = "-".join("".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(4)) for _ in range(3))
        try:
            validate_password(password, user)
        except ValidationError:
            continue
        if any(c.isdigit() for c in password):
            return password


@transaction.atomic
def renew_passwords(venues):
    """A new password for every account of these venues, for the printed sheet: [(venue, [(account,
    password)])], venues without accounts left out. The old passwords stop working at once and the
    venue's PCs are logged out (Django checks the password on every request)."""
    sheet = []
    for venue in venues:
        rows = []
        for account in venue.accounts.select_related("user"):
            password = new_password(account.user)
            account.user.set_password(password)
            account.user.save(update_fields=["password"])
            rows.append((account, password))
        if rows:
            sheet.append((venue, rows))
    return sheet


def set_venue_role(user, venue, role):
    """Move a venue account to another venue and/or role. Takes effect on its next page.

    Its „Прочетох“ confirmations (and, on another venue, what it opened) were given for the old
    venue / role: they are forgotten, so the reports never credit a venue with what it didn't do;
    they ask again instead. Returns True if anything was forgotten."""
    from stats.models import Ack, Seen

    account = VenueAccount.objects.get(user=user)
    if (account.venue_id, account.role) == (venue.pk, role):
        return False
    forgotten, _ = Ack.objects.filter(user=user).delete()
    if account.venue_id != venue.pk:
        forgotten += Seen.objects.filter(user=user).delete()[0]
    account.venue, account.role = venue, role
    account.save(update_fields=["venue", "role"])
    return bool(forgotten)


def set_active(venue, active):
    venue.is_active = active
    venue.save(update_fields=["is_active"])


@transaction.atomic
def delete_venue(venue):
    """The venue and all its accounts. Posts sent only to it stay, but no venue sees them any more."""
    users = [account.user for account in venue.accounts.select_related("user")]
    venue.delete()
    for user in users:
        user.delete()


def _training_username(name):
    """`staff` / `manager`, unless that name is somebody else's: then `training_staff` …"""
    user = get_user_model().objects.filter(username__iexact=name).first()
    return name if user is None else f"training_{name}"


def training_venue():
    """The training venue („Обучение“) with the accounts `staff` and `manager` (no passwords), when missing."""
    venue = Venue.objects.filter(is_training=True).first()
    if venue is not None:
        return venue, False
    with transaction.atomic():
        venue = Venue.objects.create(name=TRAINING_NAME, is_training=True)
        for role in (STAFF, MANAGER):
            create_account(_training_username(role), venue, role)
    return venue, True
