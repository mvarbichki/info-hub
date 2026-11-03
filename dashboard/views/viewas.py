"""„Виж като обект“: choose the venue account whose view of the site an editor wants to see
(venues/viewas.py does the rest), and end it."""

from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from venues.models import VenueAccount
from venues.viewas import SESSION_KEY, chosen_account, stop

from .common import editor_required


def _site_page(request, value):
    """A safe address on the site to go back to (not a management page), else the start page."""
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}) and value.startswith("/") \
            and not value.startswith(("/manage/", "/admin/", "/login/", "//")):
        return value
    return "/"


@editor_required
def view_as(request):
    accounts = VenueAccount.objects.select_related("venue", "user")
    error = ""
    if request.method == "POST":
        pk = request.POST.get("account", "")
        account = accounts.filter(pk=pk).first() if pk.isdigit() else None
        if account is None:
            error = "Изберете обект и потребител от списъка."
        else:
            request.session[SESSION_KEY] = account.pk
            return redirect(_site_page(request, request.POST.get("next")))
    venues = {}
    for account in accounts:
        venues.setdefault(account.venue, []).append(account)
    return TemplateResponse(request, "dashboard/view_as.html", {
        "venues": venues.items(),
        "current": chosen_account(request),
        "next": _site_page(request, request.POST.get("next") or request.GET.get("next")),
        "error": error,
    })


@require_POST
@editor_required
def end_view_as(request):
    """Back to the editor's own view, on the same page (site or Управление)."""
    stop(request)
    target = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}) and target.startswith("/"):
        return redirect(target)
    return redirect("/")
