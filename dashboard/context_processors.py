from functools import reduce
from operator import or_


def manage_bar(request):
    """Editors (and the superuser) get a bar on top of the site and of Управление (/manage/).

    Its two tabs „Сайт | Управление“ show where the editor is (`area`); Управление also has its
    own light header instead of the site's menu (base.html). Everybody else (venue accounts) sees
    the plain site (venue_mode). Wagtail's /admin/ has its own templates.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {}

    from guides.models import CategoryPage

    from .access import departments_for, is_editor

    if not is_editor(user):
        return {"venue_mode": True}
    if request.path.startswith("/admin/"):
        return {"is_editor": True}
    departments = list(departments_for(user))
    bar = {
        "area": "manage" if request.path.startswith("/manage/") else "site",
        "title": "всички раздели" if user.is_superuser else ", ".join(d.title for d in departments),
    }
    if bar["area"] == "site":
        categories = CategoryPage.objects.all()
        if not user.is_superuser:
            categories = categories.filter(reduce(or_, (categories.child_of_q(d) for d in departments)))
        # Department and category pages where "+ Добави публикация тук" is offered.
        bar["place_ids"] = {d.pk for d in departments} | set(categories.values_list("pk", flat=True))
    return {"is_editor": True, "manage_bar": bar}
