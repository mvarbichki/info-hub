"""Venues (superuser only): only the places; their accounts are in users.py."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.cache import add_never_cache_headers
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from guides.audience import posts_only_for
from venues.access import delete_venue, renew_passwords, set_active
from venues.models import Venue

from ..forms import VenueForm
from .common import head_context, superuser_required


@superuser_required
def venues(request):
    """The venues with their accounts; a form to add one."""
    form = VenueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        venue = Venue.objects.create(name=form.cleaned_data["name"])
        messages.success(request, format_html(
            "Обектът „{}“ е създаден. <a href=\"{}?new_role=staff&new_venue={}#new-user\">Добавете му потребители</a>.",
            venue.name, reverse("dashboard:users"), venue.pk,
        ))
        return redirect("dashboard:venues")

    context = head_context(request)
    items = list(Venue.objects.prefetch_related("accounts__user"))
    for venue in items:
        venue.only_here = len(posts_only_for(venue))
        venue.account_list = list(venue.accounts.all())
    context.update({"form": form, "venues": items})
    return TemplateResponse(request, "dashboard/venues.html", context)


@superuser_required
def edit_venue(request, pk):
    venue = get_object_or_404(Venue, pk=pk)
    form = VenueForm(request.POST or None, venue=venue, initial={"name": venue.name})
    if request.method == "POST" and form.is_valid():
        venue.name = form.cleaned_data["name"]
        venue.save(update_fields=["name"])
        messages.success(request, f"Обектът „{venue.name}“ е запазен.")
        return redirect("dashboard:venues")
    context = head_context(request)
    context.update({"form": form, "venue": venue})
    return TemplateResponse(request, "dashboard/venue_edit.html", context)


@superuser_required
@require_POST
def toggle_venue(request, pk):
    venue = get_object_or_404(Venue, pk=pk)
    set_active(venue, not venue.is_active)
    messages.success(request, f"„{venue.name}“ е {'пуснат отново' if venue.is_active else 'спрян: потребителите му не могат да влизат'}.")
    return redirect("dashboard:venues")


@superuser_required
@require_POST
def remove_venue(request, pk):
    venue = get_object_or_404(Venue, pk=pk)
    if venue.is_training:
        messages.error(request, "Обектът за обучение не може да се изтрие (може да се спре).")
        return redirect("dashboard:venues")
    name, count = venue.name, venue.accounts.count()
    delete_venue(venue)
    messages.success(request, f"Обектът „{name}“ е изтрит" + (f", заедно с потребителите му ({count})." if count else "."))
    return redirect("dashboard:venues")


@superuser_required
@require_POST
def password_sheet(request, pk=None):
    """New passwords for one venue (pk) or for every working venue (not the training one), shown
    once as a sheet to print. The passwords are stored only as hashes, so they can't be shown again."""
    if pk is None:
        venues = Venue.objects.filter(is_active=True, is_training=False)
    else:
        venues = [get_object_or_404(Venue, pk=pk)]
    sheet = renew_passwords(venues)
    if not sheet:
        messages.error(request, "Няма потребители, на които да се сменят паролите.")
        return redirect("dashboard:venues")
    response = TemplateResponse(request, "dashboard/password_sheet.html", {
        "sheet": sheet,
        "login_url": request.build_absolute_uri(reverse("login")),
        "accounts": sum(len(rows) for _, rows in sheet),
    })
    add_never_cache_headers(response)  # the passwords must not stay in a cache
    return response
