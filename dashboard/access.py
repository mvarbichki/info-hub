"""Who may manage what in /manage/.

The superuser manages everything. Editors (department users, „Редактор“) manage only the
departments their group „<Раздел> – редактори“ has page permissions on (see guides/departments.py).
Venue accounts (venues/access.py) only read the site.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from guides.departments import department_group
from guides.models import DepartmentPage


def departments_for(user):
    departments = DepartmentPage.objects.order_by("path")
    if user.is_superuser:
        return departments
    return departments.filter(group_permissions__group__user=user).distinct()


def is_editor(user):
    return user.is_active and (user.is_superuser or departments_for(user).exists())


def can_manage(user, page):
    """True if the page (department, category or guide) lies inside one of the user's departments."""
    if user.is_superuser:
        return True
    return departments_for(user).ancestor_of(page, inclusive=True).exists()


def editor_groups():
    return Group.objects.filter(page_permissions__page__in=DepartmentPage.objects.all()).distinct()


def set_department(user, department):
    """Make the user an editor of this one department only."""
    user.groups.remove(*editor_groups())
    user.groups.add(department_group(department))


def create_editor(username, department, password=""):
    """New editor for one department. The password (default: the username) is temporary."""
    from .models import set_must_change_password

    user = get_user_model().objects.create_user(username=username, password=password or username)
    set_department(user, department)
    set_must_change_password(user, True)
    return user
