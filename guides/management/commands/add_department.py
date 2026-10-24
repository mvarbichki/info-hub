from django.core.management.base import BaseCommand, CommandError

from guides.departments import DepartmentError, create_department
from guides.models import COLOR_CHOICES, ICON_CHOICES


class Command(BaseCommand):
    help = "Създава нов раздел: страница, група редактори с права и папка за снимки/видео. (Същото като /manage/ → Раздели.)"

    def add_arguments(self, parser):
        parser.add_argument("title", help='Име на раздела, напр. "Финанси"')
        parser.add_argument("slug", help="Кратък адрес на латиница, напр. finance")
        parser.add_argument("--description", default="")
        parser.add_argument("--color", default="blue", choices=[c for c, _ in COLOR_CHOICES])
        parser.add_argument("--icon", default="info", choices=[i for i, _ in ICON_CHOICES])

    def handle(self, *args, **options):
        try:
            department, group, created = create_department(
                options["title"], options["slug"], options["description"], options["color"], options["icon"]
            )
        except DepartmentError as error:
            raise CommandError(str(error))
        state = "Създаден" if created else "Вече съществува"
        self.stdout.write(self.style.SUCCESS(f"{state}: {department.title} ({department.url}) – група „{group.name}“"))
