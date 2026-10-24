from django.core.management import call_command
from django.core.management.base import BaseCommand

from guides.cleanup import size_of, stray_files, unused_media
from stats.tracking import purge

REVISION_DAYS = 90
# Visit/search counters older than this are deleted (the „Статистика“ tab shows up to 90 days).
STATS_DAYS = 365


class Command(BaseCommand):
    help = (
        "Изтрива неизползвани снимки, видео и файлове, стари версии на страниците (над 90 дни), "
        "изтекли сесии и статистика над година. Пуска се всяка нощ (deploy/backup.sh). С --dry-run само показва."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Само покажи какво ще се изтрие")

    def handle(self, *args, dry_run=False, **options):
        images, documents = unused_media()
        files = list(stray_files())
        freed = sum(size_of(o) for o in images + documents) + sum(p.stat().st_size for p in files)
        verb = "Ще се изтрият" if dry_run else "Изтрити"

        for obj in images + documents:
            self.stdout.write(f"  {type(obj).__name__} #{obj.pk}: {obj.title} ({obj.file.name})")
        for path in files:
            self.stdout.write(f"  файл без запис: {path}")

        if not dry_run:
            for obj in images + documents:
                obj.delete()  # Wagtail removes the file (and image renditions) from disk
            for path in files:
                path.unlink(missing_ok=True)
            call_command("purge_revisions", days=REVISION_DAYS, verbosity=0, stdout=self.stdout)
            call_command("clearsessions", stdout=self.stdout)
            purge(STATS_DAYS)

        self.stdout.write(self.style.SUCCESS(
            f"{verb}: {len(images)} снимки, {len(documents)} видео/файла, {len(files)} файла без запис"
            f" – {freed / 1048576:.1f} MB."
            + ("" if dry_run else f" Стари версии на страници (над {REVISION_DAYS} дни), изтекли сесии и статистика над {STATS_DAYS} дни са изчистени.")
        ))
