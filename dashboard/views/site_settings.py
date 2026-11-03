"""Настройки (superuser): the site's name, logo and footer. Replaces Wagtail's /admin/, which is closed."""

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from wagtail.images import get_image_model
from wagtail.models import Collection, Site

from home.models import SiteBranding

from ..forms import SiteSettingsForm
from .common import head_context, superuser_required


@superuser_required
def site_settings(request):
    branding = SiteBranding.for_site(Site.objects.get(is_default_site=True))
    initial = {"site_name": branding.site_name, "footer_text": branding.footer_text}
    form = SiteSettingsForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        old_logo = branding.logo
        if data["logo"]:
            branding.logo = get_image_model().objects.create(
                title="Лого", file=data["logo"], collection=Collection.get_first_root_node(),
            )
        elif data["remove_logo"]:
            branding.logo = None
        branding.site_name, branding.footer_text = data["site_name"], data["footer_text"]
        branding.save()
        # The logo lives in the root folder, never in a post: a replaced one isn't needed any more.
        if old_logo and old_logo != branding.logo and old_logo.collection_id == Collection.get_first_root_node().pk:
            old_logo.delete()
        messages.success(request, "Настройките са запазени.")
        return redirect("dashboard:settings")
    context = head_context(request)
    context.update({"form": form, "branding": branding, "active": "settings"})
    return TemplateResponse(request, "dashboard/site_settings.html", context)
