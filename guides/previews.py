"""PDF copies of Word, Excel and PowerPoint files, so a post can show them in the page like a PDF
(browsers can't show Office files themselves). Made with LibreOffice on upload; the download stays
the original file. Without LibreOffice, or if a file can't be converted, it is simply download-only.
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import DocumentPreview

logger = logging.getLogger(__name__)

CONVERTIBLE = {"doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "ppt", "pptx", "odp"}
# A large spreadsheet may take a while; after this the file stays download-only.
TIMEOUT_SECONDS = 120
WINDOWS_PATH = Path("C:/Program Files/LibreOffice/program/soffice.exe")


def soffice():
    """The LibreOffice program, or None. INFOHUB_SOFFICE: a path, "" = look for it, "off" = never."""
    configured = settings.INFOHUB_SOFFICE
    if configured == "off":
        return None
    if configured:
        return configured
    return shutil.which("soffice") or shutil.which("libreoffice") or (str(WINDOWS_PATH) if WINDOWS_PATH.is_file() else None)


def make_preview(document):
    """Store a PDF copy of the document if it is a Word/Excel/PowerPoint file. Returns it or None."""
    extension = document.file_extension.lower()
    program = soffice()
    if extension not in CONVERTIBLE or program is None:
        return None
    with tempfile.TemporaryDirectory(prefix="infohub-preview-") as folder:
        folder = Path(folder)
        source = folder / f"file.{extension}"
        with document.file.open("rb") as original, source.open("wb") as copy:
            shutil.copyfileobj(original, copy)
        command = [
            program, f"-env:UserInstallation={(folder / 'profile').as_uri()}",  # own profile: runs in parallel
            "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(folder), str(source),
        ]
        try:
            subprocess.run(command, capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.warning("No PDF copy of document %s: %s", document.pk, error)
            return None
        pdf = folder / "file.pdf"
        if not pdf.is_file() or not pdf.stat().st_size:
            logger.warning("No PDF copy of document %s: LibreOffice made no PDF", document.pk)
            return None
        DocumentPreview.objects.filter(document=document).delete()
        preview = DocumentPreview(document=document)
        with pdf.open("rb") as made:
            preview.file.save(f"{Path(document.file.name).stem}.pdf", File(made), save=True)
        return preview


@receiver(post_delete, sender=DocumentPreview)
def _delete_file(sender, instance, **kwargs):
    """The PDF copy goes with its row (as Wagtail does for documents), once the transaction is done."""
    if instance.file:
        transaction.on_commit(lambda: instance.file.storage.delete(instance.file.name))
