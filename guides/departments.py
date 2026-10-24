"""Create, change and remove departments (used by /manage/ → Раздели and the management commands).

A department is a DepartmentPage under the home page, plus:
- a media collection for its pictures/videos/files (linked through DepartmentMedia),
- a group „<Раздел> – редактори“ with page permissions on it. Members (editors) manage only this
  department in /manage/ (see dashboard/access.py) and have no access to the Wagtail admin.
"""

from django.contrib.auth.models import Group, Permission
from django.db import transaction

from wagtail.models import Collection, GroupCollectionPermission, GroupPagePermission

from .models import CategoryPage, DepartmentMedia, DepartmentPage, GuidePage
from .slugs import unique_slug

PAGE_PERMISSIONS = ["add_page", "change_page", "publish_page", "lock_page", "unlock_page"]
COLLECTION_PERMISSIONS = [
    ("wagtailimages", ["add_image", "change_image", "choose_image", "delete_image"]),
    ("wagtaildocs", ["add_document", "change_document", "choose_document", "delete_document"]),
]
# Addresses used by the site itself, so a department can't take them.
RESERVED_SLUGS = {"admin", "manage", "login", "search", "feedback", "read", "documents", "media", "static"}


class DepartmentError(Exception):
    """The change can't be made. The message is shown to the user as is."""


def group_name(title):
    return f"{title} – редактори"


def department_group(department):
    return Group.objects.filter(page_permissions__page=department).order_by("pk").first()


def department_collection(department):
    """The department's media collection, created (or linked by name, for old data) when missing."""
    link = DepartmentMedia.objects.filter(department=department).select_related("collection").first()
    if link:
        return link.collection
    root = Collection.get_first_root_node()
    collection = root.get_children().filter(name=department.title).first() or root.add_child(name=department.title)
    DepartmentMedia.objects.create(department=department, collection=collection)
    return collection


def _home():
    from home.models import HomePage

    home = HomePage.objects.first()
    if home is None:
        raise DepartmentError("Липсва начална страница. Изпълнете първо 'migrate'.")
    return home


def _grant_permissions(department, group, collection):
    for codename in PAGE_PERMISSIONS:
        permission = Permission.objects.get(content_type__app_label="wagtailcore", codename=codename)
        GroupPagePermission.objects.get_or_create(group=group, page=department, permission=permission)
    for app_label, codenames in COLLECTION_PERMISSIONS:
        for codename in codenames:
            permission = Permission.objects.get(content_type__app_label=app_label, codename=codename)
            GroupCollectionPermission.objects.get_or_create(group=group, collection=collection, permission=permission)
    # The Wagtail admin („Разширени настройки“) is for the superuser only.
    group.permissions.remove(Permission.objects.get(content_type__app_label="wagtailadmin", codename="access_admin"))


def create_department(title, slug="", description="", color="blue", icon="info", user=None):
    """Create (or reuse, by slug) a department with its group and media collection.

    Returns (department, group, created).
    """
    home = _home()
    with transaction.atomic():
        department = DepartmentPage.objects.child_of(home).filter(slug=slug).first() if slug else None
        created = department is None
        if created:
            slug = slug or unique_slug(home, title)
            if slug in RESERVED_SLUGS:
                raise DepartmentError(f"Адресът „/{slug}/“ се използва от сайта. Изберете друг.")
            department = DepartmentPage(title=title, slug=slug, description=description, color=color, icon=icon)
            home.add_child(instance=department)
            department.save_revision(user=user, log_action=True).publish(user=user)

        collection = department_collection(department)
        group = department_group(department)
        if group is None:
            group, _ = Group.objects.get_or_create(name=group_name(department.title))
        _grant_permissions(department, group, collection)
    return department, group, created


def update_department(department, *, title, description, color, icon, user=None):
    """Change name, description, colour and icon. The address (slug) stays, so links keep working."""
    with transaction.atomic():
        page = department.get_latest_revision_as_object()
        old_title = page.title
        page.title = page.draft_title = title
        page.description, page.color, page.icon = description, color, icon
        page.save_revision(user=user, log_action=True).publish(user=user)
        if title != old_title:
            collection = department_collection(department)
            collection.name = title
            collection.save()
            group = department_group(department)
            if group and group.name == group_name(old_title):
                group.name = group_name(title)
                group.save()
    return page


def move_department(department, direction, user=None):
    """Swap with the department above ("up") or below ("down"). The menu, the home page and the
    panel list departments in this order. At either end nothing changes; returns whether it moved."""
    siblings = list(DepartmentPage.objects.sibling_of(department).order_by("path"))
    index = siblings.index(department) + (-1 if direction == "up" else 1)
    if not 0 <= index < len(siblings):
        return False
    department.move(siblings[index], pos="left" if direction == "up" else "right", user=user)
    return True


def delete_department(department):
    """Delete an empty department with its group and media collection."""
    posts = GuidePage.objects.descendant_of(department).count()
    categories = CategoryPage.objects.child_of(department).count()
    group = department_group(department)
    users = list(group.user_set.values_list("username", flat=True)) if group else []
    if posts or categories:
        raise DepartmentError(
            f"„{department.title}“ има {posts} публикации и {categories} категории. Изтрийте ги първо."
        )
    if users:
        raise DepartmentError(
            f"„{department.title}“ се управлява от: {', '.join(users)}. Преместете ги в друг раздел или ги изтрийте (Потребители)."
        )
    with transaction.atomic():
        link = DepartmentMedia.objects.filter(department=department).select_related("collection").first()
        department.delete()
        if group:
            group.delete()
        if link:
            link.collection.delete()  # nothing uses its media any more; Wagtail removes the files
