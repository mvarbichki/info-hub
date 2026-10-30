from django.core.management.base import BaseCommand
from wagtail.documents.models import Document

from guides.previews import CONVERTIBLE, make_preview, soffice


class Command(BaseCommand):
    help = "PDF копия на Word/Excel/PowerPoint файловете, които още нямат (напр. качени преди тази функция)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Направи наново и съществуващите копия.")

    def handle(self, *args, all=False, **options):
        if soffice() is None:
            self.stderr.write("Няма LibreOffice (INFOHUB_SOFFICE): PDF копия не могат да се направят.")
            return
        documents = Document.objects.all() if all else Document.objects.filter(preview__isnull=True)
        missing = [d for d in documents if d.file_extension.lower() in CONVERTIBLE]
        made = 0
        for document in missing:
            if make_preview(document):
                made += 1
            else:
                self.stdout.write(f"  без PDF копие: {document.title} ({document.file.name})")
        self.stdout.write(self.style.SUCCESS(f"PDF копия: {made} от {len(missing)}."))
