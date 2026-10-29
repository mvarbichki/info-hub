"""Departments (superuser only)."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from guides.departments import (
    DepartmentError, create_department, delete_department, department_group, move_department, update_department,
)
from guides.models import CategoryPage, DepartmentPage, GuidePage
from guides.publishing import inactive_count

from ..forms import DepartmentForm
from .common import head_context, superuser_required


@superuser_required
def departments(request):
    form = DepartmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            department, _, _ = create_department(
                data["title"], data["slug"], data["description"], data["color"], data["icon"], user=request.user
            )
        except DepartmentError as error:
            form.add_error("slug", str(error))
        else:
            messages.success(request, format_html(
                "Разделът <a href=\"{}\">{}</a> е създаден. Добавете му потребител в „Потребители“.",
                department.url, department.title,
            ))
            return redirect("dashboard:departments")

    context = head_context(request)
    for department in context["departments"]:
        guides = GuidePage.objects.descendant_of(department)
        department.active_count = guides.live().count()
        department.inactive_count = inactive_count(department)
        department.draft_count = guides.filter(live=False, first_published_at__isnull=True).count()
        department.category_count = CategoryPage.objects.child_of(department).count()
        group = department_group(department)
        department.usernames = list(group.user_set.order_by("username").values_list("username", flat=True)) if group else []
    context.update({"form": form})
    return TemplateResponse(request, "dashboard/departments.html", context)


@superuser_required
def edit_department(request, pk):
    department = get_object_or_404(DepartmentPage, pk=pk)
    latest = department.get_latest_revision_as_object()
    form = DepartmentForm(request.POST or None, department=department, initial={
        "title": latest.title, "description": latest.description, "color": latest.color, "icon": latest.icon,
    })
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        update_department(department, title=data["title"], description=data["description"],
                          color=data["color"], icon=data["icon"], user=request.user)
        messages.success(request, f"Разделът „{data['title']}“ е запазен.")
        return redirect("dashboard:departments")
    return TemplateResponse(request, "dashboard/department_edit.html", {"form": form, "department": latest})


@superuser_required
@require_POST
def reorder_department(request, pk):
    department = get_object_or_404(DepartmentPage, pk=pk)
    if request.POST.get("direction") in ("up", "down"):
        move_department(department, request.POST["direction"], user=request.user)
    return redirect("dashboard:departments")


@superuser_required
@require_POST
def remove_department(request, pk):
    department = get_object_or_404(DepartmentPage, pk=pk)
    title = department.title
    try:
        delete_department(department)
    except DepartmentError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Разделът „{title}“ е изтрит.")
    return redirect("dashboard:departments")
