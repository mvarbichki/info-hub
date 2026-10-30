"""The site is on the internet but private: every page and file needs a login.

Django's LoginRequiredMiddleware sends anyone not logged in to /login/. Uploaded files
(/media/...) go through serve_media, so pictures and videos can't be opened by a direct link
either. Only the logo is public, for the login page. A venue account gets only the files of the
posts it may see (guides/audience.py), so a manager-only post's pictures don't reach the staff.
"""

import mimetypes
import os
import re
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponse, HttpResponseNotModified, StreamingHttpResponse
from django.shortcuts import render
from django.utils._os import safe_join
from django.utils.http import http_date
from django.views.static import was_modified_since

RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 64 * 1024
# Shown in the browser; anything else is downloaded.
INLINE_TYPES = ("image/", "video/", "audio/", "application/pdf")


class NoIndexMiddleware:
    """Search engines must not list anything (also files, which have no <meta> tag)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        return response


@login_not_required
def robots_txt(request):
    return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")


def csrf_failure(request, reason=""):
    """A form came back with an expired security token (CSRF_FAILURE_VIEW): explained in
    Bulgarian instead of Django's English technical page."""
    return render(request, "403_csrf.html", status=403)


def _is_logo(path):
    from home.models import SiteBranding
    from wagtail.images.models import Image, Rendition

    logos = SiteBranding.objects.exclude(logo=None).values_list("logo_id", flat=True)
    return (
        Rendition.objects.filter(image_id__in=logos, file=path).exists()
        or Image.objects.filter(pk__in=logos, file=path).exists()
    )


def _may_open(user, path):
    """Content managers open every file; anybody else only the files of posts they may see."""
    from dashboard.access import is_editor
    from guides.audience import visible_media
    from guides.models import DocumentPreview
    from wagtail.documents.models import Document
    from wagtail.images.models import Image, Rendition

    if is_editor(user):
        return True
    images, documents = visible_media(user)
    image_ids = set(Image.objects.filter(file=path).values_list("pk", flat=True))
    image_ids |= set(Rendition.objects.filter(file=path).values_list("image_id", flat=True))
    document_ids = set(Document.objects.filter(file=path).values_list("pk", flat=True))
    document_ids |= set(DocumentPreview.objects.filter(file=path).values_list("document_id", flat=True))
    return bool(image_ids & images or document_ids & documents)


@login_not_required
def serve_media(request, path):
    """An uploaded file, for logged-in users. Supports range requests (jumping around in a video)."""
    logo = _is_logo(path)
    if not request.user.is_authenticated and not logo:
        return redirect_to_login(request.get_full_path())
    if not logo and not _may_open(request.user, path):
        raise Http404
    try:
        full_path = safe_join(settings.MEDIA_ROOT, path)
    except Exception:
        raise Http404
    if not os.path.isfile(full_path):
        raise Http404

    content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
    if settings.INFOHUB_MEDIA_ACCEL_REDIRECT:
        # nginx sends the file itself (also ranges), from an internal location.
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = settings.INFOHUB_MEDIA_ACCEL_REDIRECT.rstrip("/") + "/" + quote(path)
    else:
        response = _file_response(request, full_path, content_type)
        if response.status_code in (304, 416):
            return response

    response["Cache-Control"] = "private, max-age=604800"  # replaced files get new names
    response["X-Content-Type-Options"] = "nosniff"
    if content_type == "application/pdf":
        response["X-Frame-Options"] = "SAMEORIGIN"  # shown inside a post (infohub.js); else DENY
    if not content_type.startswith(INLINE_TYPES):
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(os.path.basename(full_path))}"
    return response


def _file_response(request, full_path, content_type):
    stat = os.stat(full_path)
    if not was_modified_since(request.headers.get("If-Modified-Since"), stat.st_mtime):
        return HttpResponseNotModified()

    size = stat.st_size
    start, end, status = 0, size - 1, 200
    match = RANGE.match(request.headers.get("Range", "").strip())
    if match and size and (match.group(1) or match.group(2)):
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:  # "bytes=-500": the last 500 bytes
            start = max(size - int(last), 0)
        if start > end:
            return HttpResponse(status=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206

    response = StreamingHttpResponse(_read(full_path, start, end - start + 1), status=status, content_type=content_type)
    response["Content-Length"] = str(end - start + 1)
    response["Accept-Ranges"] = "bytes"
    response["Last-Modified"] = http_date(stat.st_mtime)
    if status == 206:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    return response


def _read(full_path, start, length):
    with open(full_path, "rb") as f:
        f.seek(start)
        while length > 0:
            chunk = f.read(min(CHUNK, length))
            if not chunk:
                break
            length -= len(chunk)
            yield chunk
