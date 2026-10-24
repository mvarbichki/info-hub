from django.urls import reverse

from wagtail import hooks
from wagtail.admin.menu import MenuItem


@hooks.register("register_admin_menu_item")
def register_manage_link():
    """Link from the Wagtail admin back to the /manage/ panel, at the top of the menu."""
    return MenuItem("← Управление", reverse("dashboard:index"), icon_name="upload", order=1)
