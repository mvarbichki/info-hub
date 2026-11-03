"""„Виж като обект“: an editor looks at the site exactly as one venue account sees it.

The editor picks an account in /manage/view-as/; its id is kept in the session. On site pages
(not /manage/, /login/, files) ViewAsMiddleware then puts that account in `request.user`, so every
list, search, post, file and label goes through the usual rules (guides/audience.py) for it: what it
may see, what is still „Ново“ for it, what its venue confirmed. Nothing is recorded meanwhile:
the account object carries `infohub_viewed_by` (the editor), counted_reader() and GuidePage.serve
skip views, „Ново“ and searches for it, and every POST on the site is refused (votes, „Прочетох“),
so a preview never speaks for the venue. Management pages always run as the editor, and so do
files (/media/, /documents/): Управление shows thumbnails of any post while a look is on, and the
venue's pages only link the venue's own files anyway.
"""

from django.http import HttpResponseForbidden, JsonResponse

from .models import VenueAccount

SESSION_KEY = "infohub_view_as"
# Pages that always run as the logged-in editor.
OWN_PAGES = ("/manage/", "/admin/", "/login/", "/static/", "/robots.txt", "/media/", "/documents/")
REFUSED = "Преглед като обект: нищо не се изпраща и не се записва."


def viewed_by(user):
    """The editor looking through this venue account, else None."""
    return getattr(user, "infohub_viewed_by", None)


def chosen_account(request):
    """The VenueAccount the editor is looking through (from the session), or None."""
    pk = request.session.get(SESSION_KEY) if hasattr(request, "session") else None
    if not pk:
        return None
    return VenueAccount.objects.select_related("venue", "user").filter(pk=pk).first()


def stop(request):
    request.session.pop(SESSION_KEY, None)


class ViewAsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # A draft's „Преглед“ (Wagtail's dummy request, is_dummy) is always the editor's own view.
        if (SESSION_KEY in request.session and request.user.is_authenticated and not request.path.startswith(OWN_PAGES)
                and not getattr(request, "is_dummy", False)):
            from dashboard.access import is_editor

            editor = request.user
            account = chosen_account(request)
            if account is None or not is_editor(editor):  # account deleted, or no longer an editor
                stop(request)
            else:
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                        return JsonResponse({"error": REFUSED}, status=403)
                    return HttpResponseForbidden(REFUSED, content_type="text/plain; charset=utf-8")
                viewer = account.user
                viewer.infohub_viewed_by = editor
                request.user = viewer
                request.view_as = account
        return self.get_response(request)
