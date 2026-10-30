"""Keep the uploads folder from growing: find media nothing uses any more, and report disk use.

Deleting a post deletes its media (see publishing.py). This catches the rest: media an edit
replaced, once no saved version of the post uses it (revisions are kept 90 days), files uploaded in
the editor but never saved in a post (removed again, or the page was closed), and files on disk
whose database row is gone. Run nightly by `manage.py cleanup_media`.
"""

import os
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.utils import timezone
from wagtail.documents.models import Document
from wagtail.images.models import Image, Rendition
from wagtail.models import Collection, Page, ReferenceIndex, Revision

from home.models import SiteBranding

from .models import DepartmentMedia, DepartmentPage, GuidePage

# Something uploaded in the last day may belong to a post that is still being written.
GRACE = timedelta(days=1)
MEDIA_FOLDERS = ("original_images", "images", "documents")


def upload_collections():
    """Collections the editor uploads into: one per department. Others are left alone."""
    return Collection.objects.filter(pk__in=DepartmentMedia.objects.values_list("collection_id", flat=True))


def used_media():
    """Image and document ids used by any guide: the published version or any saved revision."""
    images, documents = set(), set()
    versions = list(GuidePage.objects.values_list("uploaded_media", flat=True))
    revisions = Revision.objects.filter(base_content_type=ContentType.objects.get_for_model(Page))
    versions += [c.get("uploaded_media") or {} for c in revisions.values_list("content", flat=True)]
    for used in versions:
        images.update(used.get("images", []))
        documents.update(used.get("documents", []))
    images.update(SiteBranding.objects.exclude(logo=None).values_list("logo_id", flat=True))
    return images, documents


def unused_media():
    """(images, documents) in the upload collections that nothing refers to and are older than a day."""
    used_images, used_documents = used_media()
    cutoff = timezone.now() - GRACE
    collections = upload_collections()
    candidates = [
        Image.objects.filter(collection__in=collections, created_at__lt=cutoff).exclude(pk__in=used_images),
        Document.objects.filter(collection__in=collections, created_at__lt=cutoff).exclude(pk__in=used_documents),
    ]
    # Also keep anything placed by hand in a page through the Wagtail admin.
    return [[obj for obj in queryset if not ReferenceIndex.get_references_to(obj).exists()] for queryset in candidates]


def stray_files():
    """Files in the media folders that no image, rendition or document points to (older than a day)."""
    known = set()
    for model in (Image, Rendition, Document):
        known.update(Path(name).as_posix() for name in model.objects.values_list("file", flat=True))
    cutoff = (timezone.now() - GRACE).timestamp()
    root = Path(settings.MEDIA_ROOT)
    for folder in MEDIA_FOLDERS:
        for path in (root / folder).rglob("*"):
            if path.is_file() and path.relative_to(root).as_posix() not in known and path.stat().st_mtime < cutoff:
                yield path


def size_of(obj):
    try:
        return obj.get_file_size() or 0
    except Exception:
        return 0


def _collection_size(collection):
    total = 0
    for model in (Image, Document):
        objects = model.objects.filter(collection=collection)
        total += objects.aggregate(total=Sum("file_size"))["total"] or 0
        total += sum(size_of(o) for o in objects.filter(file_size=None))  # fills in the stored size
    return total


def storage_report():
    """Disk use for the panel: space per department and free space on the server's disk."""
    links = {m.department_id: m.collection for m in DepartmentMedia.objects.select_related("collection")}
    rows = [(d.title, _collection_size(links[d.pk]) if d.pk in links else 0) for d in DepartmentPage.objects.order_by("path")]
    disk = shutil.disk_usage(settings.MEDIA_ROOT if os.path.exists(settings.MEDIA_ROOT) else settings.BASE_DIR)
    return {"rows": rows, "total": sum(r[1] for r in rows), "disk_total": disk.total, "disk_free": disk.free,
            "free_percent": round(disk.free * 100 / disk.total), "low": disk.free / disk.total < 0.15}
