from functools import reduce
from operator import or_


def manage_bar(request):
    """'Manage mode' on the site: editors (and the superuser) get a bar with their shortcuts (is_editor).

    Everybody else (venue accounts) sees the plain site (venue_mode).
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {}

    from guides.models import CategoryPage

    from .access import departments_for, is_editor

    if not is_editor(user):
        return {"venue_mode": True}
    if request.path.startswith(("/manage/", "/admin/")):
        return {"is_editor": True}
    departments = list(departments_for(user))
    categories = CategoryPage.objects.all()
    if not user.is_superuser:
        categories = categories.filter(reduce(or_, (categories.child_of_q(d) for d in departments)))
    return {
        "is_editor": True,
        "manage_bar": {
            "title": "всички раздели" if user.is_superuser else ", ".join(d.title for d in departments),
            # Department and category pages where "+ Добави публикация тук" is offered.
            "place_ids": {d.pk for d in departments} | set(categories.values_list("pk", flat=True)),
        }
    }
