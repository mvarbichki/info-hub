from django.apps import AppConfig
from wagtail.users.apps import WagtailUsersAppConfig


class DashboardConfig(AppConfig):
    default = True  # apps.py has more than one config
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"
    verbose_name = "Управление"


class InfoHubUsersConfig(WagtailUsersAppConfig):
    """wagtail.users with optional name/e-mail (accounts aren't per person)."""

    user_viewset = "dashboard.wagtail_users.InfoHubUserViewSet"

    def ready(self):
        super().ready()
        from wagtail.admin.views.account import NameEmailSettingsPanel

        from .wagtail_users import OptionalNameEmailForm

        NameEmailSettingsPanel.form_class = OptionalNameEmailForm
