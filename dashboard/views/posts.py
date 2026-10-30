"""Posts: the list, the editor (publish or save a draft), preview, who read it, uploads, archive and delete."""

from functools import reduce
from operator import or_

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from wagtail.documents.models import Document
from wagtail.images.models import Image
from wagtail.models import Page

from guides.audience import accounts_for, summary
from guides.cleanup import storage_report
from guides.departments import department_collection
from guides.editor import EditorError, parse, to_editor
from guides.media import UploadRefused, describe, file_extensions, save_upload
from guides.models import AUDIENCE_ALL, AUDIENCE_MANAGERS, AUDIENCE_STAFF, DepartmentPage, GuidePage
from guides.publishing import InactiveLimitReached, delete_guide, inactive_count, save_guide, set_visible
from stats.reading import ack_counts, report
from venues.models import MANAGER, Venue

from ..access import can_manage, departments_for
from ..forms import GuideForm
from .common import back_to_list, editor_required, head_context, managed_page


@editor_required
def index(request):
    context = head_context(request)
    departments = context["departments"]
    guides = GuidePage.objects.all().order_by("-latest_revision_created_at")
    if not request.user.is_superuser:
        guides = guides.filter(reduce(or_, (guides.descendant_of_q(d) for d in departments)))
    query = request.GET.get("q", "").strip()
    if query:
        # In Python: SQLite's icontains only ignores the case of Latin letters („ит“ ≠ „ИТ“ there).
        needle = query.casefold()
        guides = guides.filter(pk__in=[pk for pk, title in guides.values_list("pk", "draft_title") if needle in title.casefold()])
    department_id = request.GET.get("department", "")
    department = next((d for d in departments if str(d.pk) == department_id), None)
    if department:
        guides = guides.descendant_of(department)
    status = request.GET.get("status", "")
    if status == "active":
        guides = guides.filter(live=True)
    elif status in ("inactive", "draft"):
        guides = guides.filter(live=False, first_published_at__isnull=status == "draft")

    limit = settings.INFOHUB_MAX_INACTIVE_PER_DEPARTMENT
    inactive = [(d, inactive_count(d)) for d in departments]

    shown = Paginator(guides, 30).get_page(request.GET.get("page"))
    # „Прочетох: 12 / 46“ for the posts that ask for it (the training venue doesn't count).
    acks = ack_counts([g for g in shown if g.needs_ack])
    for guide in shown:
        if guide.needs_ack:
            guide.acks = acks.get(guide.pk, 0)
            guide.ack_total = accounts_for(guide).exclude(venue__is_training=True).count()
    context.update({
        "guides": shown,
        "query": query,
        "department_id": department_id,
        "status": status,
        "inactive": [(d, n, n >= limit) for d, n in inactive],
        "inactive_limit": limit,
        "storage": storage_report() if request.user.is_superuser else None,
    })
    return TemplateResponse(request, "dashboard/index.html", context)


def _posted_blocks(raw):
    """The blocks sent back after an error, so nothing typed or uploaded is lost."""
    try:
        return parse(raw)
    except EditorError:
        return []


def _revision(request, page):
    """The older version asked for with ?revision=<id> (История), or None."""
    wanted = request.GET.get("revision", "")
    if page is None or not wanted:
        return None
    if not wanted.isdigit():
        raise Http404
    return get_object_or_404(page.revisions.select_related("user"), pk=wanted)


def _missing_media(revision):
    """How many pictures/files of an older version no longer exist."""
    used = revision.content.get("uploaded_media") or {}
    images, documents = set(used.get("images", [])), set(used.get("documents", []))
    return (len(images) - Image.objects.filter(pk__in=images).count()
            + len(documents) - Document.objects.filter(pk__in=documents).count())


@editor_required
def edit(request, pk=None):
    """The post editor: a new post (no pk) or an existing one; ?revision=<id> fills it with an older
    version (История), which is brought back only when it is saved."""
    page = managed_page(request, GuidePage, pk) if pk else None
    latest = page.get_latest_revision_as_object() if page else None
    revision = _revision(request, page)
    first_publish = page is None or page.is_draft  # „Публикувано“, not „Запазено“
    if request.method == "POST":
        form = GuideForm(request.POST, user=request.user)
        blocks = _posted_blocks(request.POST.get("body"))
        if form.is_valid():
            data = form.cleaned_data
            if "is_pinned" in data:
                is_pinned, pinned_until = data["is_pinned"], data["pinned_until"]
            elif latest is not None:  # „Важно“ is the superuser's: a department user's edit keeps it
                is_pinned, pinned_until = latest.is_pinned, latest.pinned_until
            else:
                is_pinned, pinned_until = False, None
            try:
                saved = save_guide(
                    user=request.user, page=page, parent=form.parent_page(),
                    title=data["title"], summary=data["summary"], kind=data["kind"],
                    is_pinned=is_pinned, pinned_until=pinned_until, body=data["body"], audience=data["audience"],
                    needs_ack=data["needs_ack"], publish=request.POST.get("action") != "draft",
                )
            except EditorError as error:
                form.add_error("body", str(error))  # shown in the content part
            except InactiveLimitReached as error:
                form.add_error("place", str(error))
            else:
                if saved.is_draft or saved.has_unpublished_changes and saved.live:
                    messages.success(request, format_html(
                        "Черновата на „{}“ е запазена. Обектите {}. <a href=\"{}\" target=\"_blank\">Преглед ↗</a>",
                        saved.draft_title,
                        "още не я виждат" if saved.is_draft else "виждат публикуваната версия, докато не натиснете „Публикувай“",
                        reverse("dashboard:preview", args=[saved.pk]),
                    ))
                    return redirect("dashboard:update", saved.pk)
                if saved.live:
                    messages.success(request, format_html(
                        "{}: <a href=\"{}\">{}</a>. Вижда се от: {}.",
                        "Публикувано" if first_publish else "Запазено", saved.url, saved.title, summary(GuidePage.objects.get(pk=saved.pk)),
                    ))
                else:
                    messages.success(request, f"„{saved.title}“ е запазена. Тя е архивирана и не се вижда на сайта.")
                return redirect("dashboard:index")
    elif latest is not None:
        shown = revision.as_object() if revision else latest
        venues = [v.pk for v in shown.venues.all()]
        form = GuideForm(user=request.user, initial={
            "title": shown.title,
            "summary": shown.summary,
            "place": str(page.get_parent().pk),
            "kind": shown.kind,
            "is_pinned": shown.is_pinned,
            "pinned_until": shown.pinned_until,
            "all_venues": shown.audience == AUDIENCE_ALL,
            "staff_venues": venues if shown.audience == AUDIENCE_STAFF else [],
            "manager_venues": venues if shown.audience == AUDIENCE_MANAGERS else [],
            "needs_ack": shown.needs_ack,
        })
        blocks = to_editor(shown.body)
    else:
        # "+ Добави публикация тук" on the site opens the editor with that department/category chosen.
        form = GuideForm(user=request.user, initial={"kind": "guide", "place": request.GET.get("place", "")})
        blocks = []

    return TemplateResponse(request, "dashboard/edit.html", {
        "form": form,
        "guide": latest,
        "has_draft": page is not None and (page.is_draft or page.live and page.has_unpublished_changes),
        "restoring": revision,
        "missing_media": _missing_media(revision) if revision else 0,
        "venue_rows": _audience_rows(form),
        "audience_errors": [e for name in ("all_venues", "staff_venues", "manager_venues") for e in form[name].errors],
        "editor_config": {
            "blocks": blocks,
            "uploadUrl": reverse("dashboard:upload"),
            "limits": settings.INFOHUB_LIMITS_MB,
            "fileTypes": file_extensions(),
        },
    })


def _audience_rows(form):
    """The venues for the picker with what is ticked (from the posted form or the post)."""
    staff = {str(pk) for pk in form["staff_venues"].value() or []}
    managers = {str(pk) for pk in form["manager_venues"].value() or []}
    return [
        {"venue": v, "staff": str(v.pk) in staff, "manager": str(v.pk) in managers}
        for v in Venue.objects.all()
    ]


@editor_required
@require_POST
def upload(request):
    """One picture, video or file from the editor. Answers {"item": ..., "warning": ...} or {"error": ...}."""
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return JsonResponse({"error": "Няма избран файл."}, status=400)
    place = Page.objects.filter(pk=request.POST.get("place") or 0).first()
    department = DepartmentPage.objects.ancestor_of(place, inclusive=True).first() if place else None
    if department is None or not can_manage(request.user, department):
        department = departments_for(request.user).first()
    try:
        obj, warning = save_upload(uploaded, request.POST.get("kind"), department_collection(department), request.user)
    except UploadRefused as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse({"item": describe(obj), "warning": warning})


@editor_required
def preview(request, pk):
    """The latest version (e.g. a draft), or an older one (?revision=<id>), as the site would show it,
    for the editor only."""
    page = managed_page(request, GuidePage, pk)
    revision = _revision(request, page)
    shown = revision.as_object() if revision else page.get_latest_revision_as_object()
    return shown.make_preview_request(request, shown.default_preview_mode)


@editor_required
def reads(request, pk):
    """Which venue accounts opened the post and, if it asks for it, confirmed „Прочетох“."""
    page = managed_page(request, GuidePage, pk)
    rows = report(page)
    context = head_context(request)
    context.update({
        "guide": page,
        "audience": summary(page),
        "rows": rows,
        "opened": sum(1 for _, seen, _ in rows if seen),
        "acked": sum(1 for _, _, acked in rows if acked),
        "missing": _not_confirmed(rows) if page.needs_ack else [],
    })
    return TemplateResponse(request, "dashboard/reads.html", context)


def _not_confirmed(rows):
    """„Перник (управител)“, „Варна (служители, управител)“ … for the accounts without „Прочетох“."""
    missing = {}
    for account, _, acked in rows:
        if not acked:
            label = "управител" if account.role == MANAGER else "служители"
            missing.setdefault(account.venue.name, []).append(label)
    return [f"{name} ({', '.join(dict.fromkeys(roles))})" for name, roles in missing.items()]


@editor_required
@require_POST
def toggle(request, pk):
    page = managed_page(request, GuidePage, pk)
    archive, draft = page.live, page.is_draft
    try:
        set_visible(page, not archive, request.user)
    except InactiveLimitReached as error:
        messages.error(request, str(error))
    else:
        done = "архивирана (не се вижда на сайта)" if archive else "публикувана" if draft else "отново на сайта"
        messages.success(request, f"„{page.draft_title}“ е {done}.")
    return back_to_list(request)


@editor_required
@require_POST
def delete(request, pk):
    page = managed_page(request, GuidePage, pk)
    title = page.draft_title
    delete_guide(page, request.user)
    messages.success(request, f"„{title}“ е изтрита.")
    return back_to_list(request)
