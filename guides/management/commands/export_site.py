from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand

# Logins (sessions) end with the move; the search index is database-specific and rebuilt by import_site.
SKIPPED_APPS = {"sessions", "wagtailsearch"}


class Command(BaseCommand):
    help = (
        "Записва целия сайт (обекти, потребители, раздели, публикации, статистика) в един JSON файл за "
        "преместване на друг сървър. Копирайте и папката media/. На новия сървър: import_site."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", help="напр. site.json (съдържа хешовете на паролите: пазете го и го изтрийте след това)")

    def handle(self, *args, path, **options):
        labels = [c.label for c in apps.get_app_configs() if c.label not in SKIPPED_APPS and list(c.get_models())]
        # Content types and permissions first: loading a page would otherwise create them with other ids.
        first = ["contenttypes", "auth"]
        # Opened here as UTF-8: dumpdata's own output= uses the system code page, which on Windows can't hold Cyrillic.
        with open(path, "w", encoding="utf-8") as stream:
            call_command("dumpdata", *first, *[label for label in labels if label not in first], stdout=stream, verbosity=0)
        self.stdout.write(self.style.SUCCESS(f"Записано в {path}. Копирайте го заедно с папката media/ на новия сървър."))
