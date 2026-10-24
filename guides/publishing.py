"""Create, change, archive and remove guides (used by the simple /manage/ panel)."""

from django.conf import settings
from django.db import transaction
from django.db.models import Q

from wagtail.documents.models import Document
from wagtail.images.models import Image

from .audience import EVERYBODY
from .departments import department_collection
from .editor import media_ids, parse, to_body
from .models import DepartmentPage, GuidePage
from .slugs import unique_slug


class InactiveLimitReached(Exception):
    """The department already keeps the maximum of archived posts. The message is shown as is."""


def inactive_count(department):
    """Archived posts of the department (drafts don't count: they were never published)."""
    return GuidePage.objects.descendant_of(department).filter(live=False, first_published_at__isnull=False).count()


def check_inactive_room(department, title):
    limit = settings.INFOHUB_MAX_INACTIVE_PER_DEPARTMENT
    if inactive_count(department) >= limit:
        raise InactiveLimitReached(
            f"В „{department.title}“ вече има {limit} архивирани публикации (максимумът). "
            f"Изтрийте някоя от тях, за да архивирате или преместите тук „{title}“."
        )


def _media_of(page):
    """Media ids of a guide: the published version and the latest (maybe archived) one."""
    media = {"images": set(), "documents": set()}
    for version in (page, page.get_latest_revision_as_object()):
        for key in media:
            media[key].update(version.uploaded_media.get(key, []))
    return media


def _allowed(model, user, own_ids, ids):
    """id -> object for the ids the user may put in a post: the post's own media and their own uploads."""
    objects = model.objects.filter(pk__in=ids)
    if not user.is_superuser:
        objects = objects.filter(Q(pk__in=own_ids) | Q(uploaded_by_user=user))
    return {obj.pk: obj for obj in objects}


def _store_listing(page):
    """A draft's or archived post's last saved choices on the page row too (Wagtail keeps them only in
    the revision), so the list and „Върни на сайта“ match them. Nobody sees a row that isn't live."""
    venues = list(page.venues.all())
    GuidePage.objects.filter(pk=page.pk).update(
        kind=page.kind, summary=page.summary, audience=page.audience, needs_ack=page.needs_ack,
        is_pinned=page.is_pinned, pinned_until=page.pinned_until,
    )
    through = GuidePage.venues.through
    through.objects.filter(guidepage_id=page.pk).delete()
    through.objects.bulk_create([through(guidepage_id=page.pk, venue_id=v.pk) for v in venues])


def save_guide(*, user, page=None, parent, title, summary, kind, is_pinned, pinned_until, body,
               audience=EVERYBODY, needs_ack=False, publish=True):
    """Create a new guide (page=None) or change an existing one. `body` is the editor's JSON,
    `audience` = guides.audience.normalize(...) (default: everybody).

    publish=False saves a draft: a new post stays off the site, a live one keeps showing its
    published version until the draft is published. An archived post is never published here
    (it stays archived; „Върни на сайта“ in the list).

    Raises EditorError or InactiveLimitReached. Returns the page as stored.
    """
    department = DepartmentPage.objects.ancestor_of(parent, inclusive=True).first()
    old_media = _media_of(page) if page is not None else {"images": set(), "documents": set()}
    if page is not None and not page.live and not page.is_draft and page.department.pk != department.pk:
        check_inactive_room(department, page.draft_title)  # moving an archived post

    blocks = parse(body)
    image_ids, document_ids = media_ids(blocks)
    content, images, documents = to_body(
        blocks,
        _allowed(Image, user, old_media["images"], image_ids),
        _allowed(Document, user, old_media["documents"], document_ids),
    )

    with transaction.atomic():
        # Files uploaded before the place was chosen (or of a post moved to another department).
        collection = department_collection(department)
        for obj in images + documents:
            if obj.collection_id != collection.pk:
                obj.collection = collection
                obj.save(update_fields=["collection"])
        for number, image in enumerate(images, start=1):
            image.title = f"{title} – снимка {number}"[:255]
            image.save(update_fields=["title"])

        is_new = page is None
        if is_new:
            page = GuidePage(title=title, live=False)
            page.slug = unique_slug(parent, title)
            parent.add_child(instance=page)
        else:
            page = GuidePage.objects.get(pk=page.pk)
            if page.get_parent().pk != parent.pk:
                if parent.get_children().filter(slug=page.slug).exists():
                    page.slug = unique_slug(parent, page.slug)  # the address is taken there: "kasa-2"
                    page.save(update_fields=["slug"], clean=False)
                page.move(parent, pos="last-child", user=user)
                page = GuidePage.objects.get(pk=page.pk)
            slug = page.slug
            # Start from the latest revision, so an archived page's last version is the base.
            page = page.get_latest_revision_as_object()
            page.slug = slug  # the revision may still have the address from before a move

        page.title = page.draft_title = title
        page.summary = summary
        page.body = content
        page.kind = kind
        page.is_pinned = is_pinned
        page.pinned_until = pinned_until if is_pinned else None
        page.uploaded_media = {"images": [i.pk for i in images], "documents": [d.pk for d in documents]}
        page.audience, page.venues = audience
        page.needs_ack = needs_ack

        revision = page.save_revision(user=user, log_action=True)
        if publish and (page.live or page.is_draft):
            revision.publish(user=user)
        elif not page.live:
            _store_listing(page)  # a live post's row keeps its published version until publishing

    # What the post no longer uses. Wagtail removes the files from disk.
    Image.objects.filter(pk__in=old_media["images"]).exclude(pk__in=[i.pk for i in images]).delete()
    Document.objects.filter(pk__in=old_media["documents"]).exclude(pk__in=[d.pk for d in documents]).delete()
    return GuidePage.objects.get(pk=page.pk)  # as stored now (live, first published, …)


def set_visible(page, visible, user):
    """Show (publish) or archive (unpublish) a page. Archiving a guide counts towards its
    department's limit of archived posts."""
    if not visible and page.live and isinstance(page.specific, GuidePage):
        check_inactive_room(page.specific.department, page.title)
    if visible and not page.live:  # also publishes a draft
        (page.get_latest_revision() or page.save_revision(user=user)).publish(user=user)
    elif not visible and page.live:
        page.unpublish(user=user)


def delete_guide(page):
    media = _media_of(page.specific)
    page.delete()
    Image.objects.filter(pk__in=media["images"]).delete()
    Document.objects.filter(pk__in=media["documents"]).delete()
