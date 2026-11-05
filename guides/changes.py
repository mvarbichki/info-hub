"""„Важна промяна“: an editor marks an edit of a published post as important (GuideChange).

- Every venue account that may see the post gets it again in „Нови за вас“, labelled „Обновено“,
  until it opens it (stats.reading.unread), for UNREAD_DAYS after the change.
- „Какво е променено“ (optional) is shown in a box on the post and under the card's title.
- With `reconfirm`, the managers' confirmations given before the change no longer count
  (stats.reading.COUNTS); they stay stored, Прочитания shows them as earlier.

Ticked on a draft or an archived post, the change waits (`pending`) and takes effect when the post
is published (save_guide, „Публикувай“ / „Върни на сайта“ in the list). The editor's box shows the
waiting choice; saving with the box unticked drops it. A small fix is saved without the box.
"""
from datetime import timedelta

from django.db.models import OuterRef, Subquery
from django.utils import timezone

from .models import UNREAD_DAYS, GuideChange


def pending(page):
    """The change waiting for the post to be published, or None."""
    return GuideChange.objects.filter(guide_id=page.pk, pending=True).first()


def record(page, *, user, revision, note="", reconfirm=False, published):
    """The editor's choice at a save. `published`: the save put the post on the site now; else the
    change waits for that. Replaces a waiting one."""
    GuideChange.objects.filter(guide_id=page.pk, pending=True).delete()
    return GuideChange.objects.create(
        guide_id=page.pk, revision=revision, user=user, note=note, reconfirm=reconfirm, pending=not published,
    )


def drop_pending(page):
    GuideChange.objects.filter(guide_id=page.pk, pending=True).delete()


def take_effect(page):
    """The post was just published: a waiting change counts from now."""
    GuideChange.objects.filter(guide_id=page.pk, pending=True).update(pending=False, at=timezone.now())


def since():
    """Changes older than this no longer bring a post back (like a new post in „Нови за вас“)."""
    return timezone.now() - timedelta(days=UNREAD_DAYS)


def last_change_at():
    """For annotating guides: when the latest important change took effect (None if never)."""
    return Subquery(GuideChange.objects.filter(guide=OuterRef("pk"), pending=False).order_by("-at").values("at")[:1])


def recent(request):
    """guide id -> its latest important change of the last UNREAD_DAYS, worked out once per request
    (every card on a page asks)."""
    if not hasattr(request, "_infohub_changes"):
        found = {}
        for change in GuideChange.objects.filter(pending=False, at__gte=since()).order_by("at"):
            found[change.guide_id] = change  # the latest wins
        request._infohub_changes = found
    return request._infohub_changes
