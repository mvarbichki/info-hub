"""Categories inside the departments."""

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST

from guides.models import CategoryPage, GuidePage
from guides.publishing import set_visible
from guides.slugs import unique_slug

from ..forms import CategoryForm, RenameCategoryForm, same_name
from .common import editor_required, head_context, managed_page


@editor_required
def categories(request):
    form = CategoryForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        department, title = form.cleaned_data["department"], form.cleaned_data["title"]
        if same_name(CategoryPage.objects.child_of(department), "title", title):
            form.add_error("title", "Вече има категория с това име.")
        else:
            category = CategoryPage(title=title, slug=unique_slug(department, title))
            department.add_child(instance=category)
            category.save_revision(user=request.user, log_action=True).publish(user=request.user)
            messages.success(request, f"Категорията „{title}“ е създадена в {department.title}.")
            return redirect("dashboard:categories")

    context = head_context(request)
    sections = []
    for department in context["departments"]:
        items = list(CategoryPage.objects.child_of(department))
        for category in items:
            category.guide_count = GuidePage.objects.child_of(category).count()
        sections.append((department, items))
    context.update({"form": form, "sections": sections})
    return TemplateResponse(request, "dashboard/categories.html", context)


@editor_required
@require_POST
def rename_category(request, pk):
    category = managed_page(request, CategoryPage, pk)
    form = RenameCategoryForm(request.POST)
    siblings = CategoryPage.objects.sibling_of(category, inclusive=False)
    if form.is_valid() and same_name(siblings, "title", form.cleaned_data["title"]):
        messages.error(request, f"Вече има категория „{form.cleaned_data['title']}“ в този раздел.")
    elif form.is_valid() and form.cleaned_data["title"] != category.title:
        old_title = category.title
        # The address (slug) stays the same, so links to the category and its posts keep working.
        category.title = category.draft_title = form.cleaned_data["title"]
        category.save_revision(user=request.user, log_action=True).publish(user=request.user)
        messages.success(request, f"„{old_title}“ е преименувана на „{category.title}“.")
    return redirect("dashboard:categories")


@editor_required
@require_POST
def publish_category(request, pk):
    """Publish a category left as a draft (e.g. made in /admin/). There is no "hide": the posts in a
    hidden category would still be reachable and listed, so hiding is done per post."""
    category = managed_page(request, CategoryPage, pk)
    set_visible(category, True, request.user)
    messages.success(request, f"Категорията „{category.title}“ вече се вижда на сайта.")
    return redirect("dashboard:categories")


@editor_required
@require_POST
def delete_category(request, pk):
    category = managed_page(request, CategoryPage, pk)
    count = GuidePage.objects.child_of(category).count()
    if count:
        messages.error(request, f"„{category.title}“ има {count} публикации. Преместете ги в друга категория или ги изтрийте, после изтрийте категорията.")
    else:
        category.delete()
        messages.success(request, f"Категорията „{category.title}“ е изтрита.")
    return redirect("dashboard:categories")
