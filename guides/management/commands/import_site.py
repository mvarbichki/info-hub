from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from wagtail.models import Site

from guides.models import GuidePage
from venues.models import Venue, VenueAccount


class Command(BaseCommand):
    help = (
        "Зарежда файл от export_site в тази база: всичко, което е в нея, се заменя (за нов сървър, след "
        "migrate). Иска --yes. Копирайте и папката media/."
    )

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--yes", action="store_true", help="Да, заменѝ всичко в тази база")

    def handle(self, *args, path, yes=False, **options):
        if not yes:
            raise CommandError("Това изтрива всичко в тази база и зарежда файла. Пуснете отново с --yes.")
        # Empty every table, without recreating content types and permissions: the file has them,
        # with the ids the rest of the file refers to.
        call_command("flush", interactive=False, inhibit_post_migrate=True, verbosity=0)
        call_command("loaddata", path, verbosity=0)
        Site.clear_site_root_paths_cache()  # Wagtail's cached site addresses belong to the old data
        call_command("update_index", verbosity=0, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS(
            f"Заредено: {Venue.objects.count()} обекта, {VenueAccount.objects.count()} потребителя на обекти, "
            f"{get_user_model().objects.count()} потребителя общо, {GuidePage.objects.count()} публикации."
        ))
