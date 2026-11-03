from functools import reduce
from operator import or_


def manage_bar(request):
    """Editors (and the superuser) get a bar on top of the site and of Управление (/manage/).

    Its two tabs „Сайт | Управление“ show where the editor is (`area`); Управление also has its
    own light header instead of the site's menu (base.html). While an editor looks at the site
    „като обект“ (venues/viewas.py) the bar turns red and names the account (`view_as`); the page
    itself is that account's. Everybody else (venue accounts) sees the plain site (venue_mode).
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {}

    from guides.models import CategoryPage
    from venues.viewas import chosen_account, viewed_by

    from .access import departments_for, is_editor

    editor = viewed_by(user)
    if editor:
        return {
            "view_as": request.view_as,
            "manage_bar": {"area": "site", "editor": editor},
        }
    if not is_editor(user):
        return {"venue_mode": True}
    departments = list(departments_for(user))
    bar = {
        "area": "manage" if request.path.startswith("/manage/") else "site",
        "title": "всички раздели" if user.is_superuser else ", ".join(d.title for d in departments),
        "editor": user,
    }
    if bar["area"] == "site":
        categories = CategoryPage.objects.all()
        if not user.is_superuser:
            categories = categories.filter(reduce(or_, (categories.child_of_q(d) for d in departments)))
        # Department and category pages where "+ Добави публикация тук" is offered.
        bar["place_ids"] = {d.pk for d in departments} | set(categories.values_list("pk", flat=True))
    else:
        bar["view_as"] = chosen_account(request)  # still on for the site: „Край на прегледа“ here too
        # a post was just saved: its autosaved copy in the browser can go (infohub.js)
        bar["autosave_saved"] = request.session.pop("infohub_autosave_saved", "")
    return {"is_editor": True, "manage_bar": bar}
