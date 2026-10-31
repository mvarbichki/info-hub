"""The site is on the internet but private: every page and file needs a login.

Django's LoginRequiredMiddleware sends anyone not logged in to /login/. Uploaded files
(/media/...) go through serve_media, so pictures and videos can't be opened by a direct link
either. Only the logo is public, for the login page. A venue account gets only the files of the
posts it may see (guides/audience.py), so a manager-only post's pictures don't reach the staff.
"""

import mimetypes
import os
import re
from urllib.parse import quote, urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponse, HttpResponseNotModified, StreamingHttpResponse
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils._os import safe_join
from django.utils.cache import add_never_cache_headers, patch_cache_control
from django.utils.http import http_date, url_has_allowed_host_and_scheme
from django.views.static import was_modified_since

RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 64 * 1024
# Shown in the browser; anything else is downloaded.
INLINE_TYPES = ("image/", "video/", "audio/", "application/pdf")
# The post editor (also with ?place=…): its form posts to the page itself.
EDITOR_PAGE = re.compile(r"^/manage/(new|\d+)/(\?|$)")
LOGOUT_PAGE = re.compile(r"^/(manage|admin)/logout/")


def _form_page(request):
    """The page a form was sent from (same site, from the Referer), or ""."""
    referer = request.META.get("HTTP_REFERER", "")
    if not url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return ""
    parts = urlsplit(referer)
    if parts.path == reverse("login"):
        return ""
    return parts.path + (f"?{parts.query}" if parts.query else "")


class LoginRequired(LoginRequiredMiddleware):
    """Django's LoginRequiredMiddleware, but a button pressed after the session ended (a POST:
    „Прочетох“, „Архивирай“…) comes back, after the login, to the page it was on, not to the
    button's address: opened as a page, that would be an empty 405."""

    def handle_no_permission(self, request, view_func):
        if request.method in ("GET", "HEAD"):
            return super().handle_no_permission(request, view_func)
        page = _form_page(request) or request.get_full_path()
        return redirect_to_login(page, resolve_url(self.get_login_url(view_func)), self.get_redirect_field_name(view_func))


class PageMiddleware:
    """Common rules for every page:

    - Logged-in pages aren't kept by the browser (no-store): after „Изход“ the Back button can't show
      the last person's page, and Back never shows an old list. The post editor only revalidates
      (private, no-cache), so Back after a failed save still finds the text typed in it.
    - A button-only address opened as a page (an old link, a bookmark) goes to the start page
      (through the login page) instead of an empty "405 Method Not Allowed".
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 405 and request.method == "GET":
            return redirect("login")  # logged in: Login sends you on to your start page
        if response.get("Content-Type", "").startswith("text/html") and not response.has_header("Cache-Control"):
            if EDITOR_PAGE.match(request.get_full_path()):
                patch_cache_control(response, private=True, no_cache=True)
            else:
                add_never_cache_headers(response)
        return response


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
    Bulgarian instead of Django's English technical page.

    Login and logout have nothing to lose, so they get a simpler way on: an old login page (e.g. a
    second tab after logging in in the first) goes to the login page, which sends a logged-in user on
    to the start page. An old „Изход“ button (after a login in another tab) gets a working „Изход“
    button: an unchecked request never logs anybody out (a venue PC doesn't know its password)."""
    if request.path == reverse("login"):
        if not request.user.is_authenticated:
            messages.info(request, "Страницата за вход беше стара. Влезте отново.")
        return redirect(request.get_full_path())
    if LOGOUT_PAGE.match(request.path):
        if not request.user.is_authenticated:
            return redirect("login")  # already out
        return render(request, "403_csrf.html", {"logout": True}, status=403)
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
