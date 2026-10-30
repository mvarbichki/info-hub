from django.apps import AppConfig


class GuidesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "guides"
    verbose_name = "Ръководства"

    def ready(self):
        from . import previews  # noqa: F401  (deletes a PDF copy's file with its row)
