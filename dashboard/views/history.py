"""История: the saved versions of a post (look at one, load it into the editor to bring it back) and
who did what (Wagtail's log of page actions); „Последни промени“ across all posts."""

from functools import reduce
from operator import or_

from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.template.response import TemplateResponse
from wagtail.models import PageLogEntry

from guides.models import GuidePage

from .common import editor_required, head_context, managed_page

ACTIONS = {
    "wagtail.create": "Създадена",
    "wagtail.edit": "Запазена",
    "wagtail.publish": "Публикувана",
    "wagtail.unpublish": "Архивирана",
    "wagtail.move": "Преместена",
    "wagtail.rename": "Преименувана",
    "wagtail.revert": "Върната по-стара версия",
    "wagtail.delete": "Изтрита",
}
DELETED_USER = "изтрит потребител"


def _who(user, user_id):
    return user.username if user else DELETED_USER if user_id else "—"


@editor_required
def history(request, pk):
    page = managed_page(request, GuidePage, pk)
    revisions = {r.pk: r for r in page.revisions.select_related("user")}
    rows, shown = [], set()
    for entry in PageLogEntry.objects.filter(page_id=page.pk, action__in=ACTIONS).select_related("user"):
        revision = revisions.get(entry.revision_id) if entry.revision_id not in shown else None
        if revision:
            shown.add(revision.pk)
        rows.append({"when": entry.timestamp, "who": _who(entry.user, entry.user_id), "what": ACTIONS[entry.action], "revision": revision})
    for revision in revisions.values():  # versions saved without a log entry (older data)
        if revision.pk not in shown:
            rows.append({"when": revision.created_at, "who": _who(revision.user, revision.user_id), "what": ACTIONS["wagtail.edit"], "revision": revision})
    rows.sort(key=lambda row: row["when"], reverse=True)
    context = head_context(request)
    context.update({
        "guide": page,
        "rows": rows,
        "latest_id": page.latest_revision_id,
        "live_id": page.live_revision_id if page.live else None,
    })
    return TemplateResponse(request, "dashboard/history.html", context)


@editor_required
def activity(request):
    """Последни промени: who did what to which post. A department user sees their department's posts;
    the superuser also sees deleted ones."""
    entries = PageLogEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(GuidePage), action__in=ACTIONS
    ).select_related("user")
    context = head_context(request)
    if not request.user.is_superuser:
        guides = GuidePage.objects.filter(reduce(or_, (GuidePage.objects.descendant_of_q(d) for d in context["departments"])))
        entries = entries.filter(page_id__in=list(guides.values_list("pk", flat=True)))
    shown = Paginator(entries, 50).get_page(request.GET.get("page"))
    existing = set(GuidePage.objects.filter(pk__in=[e.page_id for e in shown]).values_list("pk", flat=True))
    context["rows"] = shown
    context["entries"] = [
        {"when": e.timestamp, "who": _who(e.user, e.user_id), "what": ACTIONS[e.action], "title": e.label,
         "page_id": e.page_id if e.page_id in existing else None}
        for e in shown
    ]
    return TemplateResponse(request, "dashboard/activity.html", context)
