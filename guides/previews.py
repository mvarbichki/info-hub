"""PDF copies of Word, Excel, PowerPoint, text and CSV files, so a post can show them in the page like a PDF
(browsers can't show Office files themselves, and only download text and CSV). Made with LibreOffice on upload; the download stays
the original file. Without LibreOffice, or if a file can't be converted, it is simply download-only.
"""

import codecs
import collections
import csv
import logging
import math
import re
import shutil
import subprocess
import tempfile
import time
import zlib
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import DocumentPreview

logger = logging.getLogger(__name__)

CONVERTIBLE = {"doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "ppt", "pptx", "odp", "txt", "csv"}
SPREADSHEETS = {"xls", "xlsx", "ods", "csv"}
# A sheet on one page of its own size: printed onto A4, a wide table is cut into several pages.
WHOLE_SHEETS = 'pdf:calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}'
# A very long sheet is shrunk to fit the largest PDF page; the viewer zooms back at most 5×, so text
# below this size (in points, normal is 10) stays unreadable: such a sheet is shown on A4 pages instead.
READABLE_TEXT_PT = 2
# Text and CSV are read as UTF-8; older Bulgarian files may be Windows-1251. „Unicode“ files from
# Excel or Notepad are UTF-16 and start with its byte order mark.
TEXT_ENCODINGS = ("utf-8-sig", "cp1251")
UTF16_MARKS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
CSV_SEPARATORS = ",;\t|"
# A large spreadsheet may take a while; after this (for all tries together) the file stays download-only.
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


def _as_utf8(source):
    """Rewrite a text/CSV file as UTF-8 (LibreOffice is told so) and return its text."""
    data = source.read_bytes()
    encodings = ("utf-16",) if data.startswith(UTF16_MARKS) else TEXT_ENCODINGS
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    source.write_text(text, encoding="utf-8", newline="")  # line ends as they were
    return text


def _input_filter(source, extension):
    """How LibreOffice reads a text or CSV file (it would guess the encoding and the separator)."""
    if extension == "txt":
        _as_utf8(source)
        return ["--infilter=Text (encoded):UTF8"]
    if extension == "csv":
        sample = _as_utf8(source)[:8192]
        try:
            separator = csv.Sniffer().sniff(sample, delimiters=CSV_SEPARATORS).delimiter
        except csv.Error:
            separator = ","
        # separator, text quote ("), UTF-8 (76), first line, -, -, quoted as text, dates etc. as written
        return [f"--infilter=Text - txt - csv (StarCalc):{ord(separator)},34,76,1,,,true,false"]
    return []


def _convert(base, target, source, deadline):
    timeout = deadline - time.monotonic()
    if timeout <= 0:
        raise subprocess.TimeoutExpired(base[0], TIMEOUT_SECONDS)
    # --convert-to must come before --outdir: the other way round LibreOffice converts nothing and waits
    command = [*base, "--convert-to", target, "--outdir", str(source.parent), str(source)]
    subprocess.run(command, capture_output=True, timeout=timeout, check=False)


def _text_size(pdf):
    """The most common font size in the PDF's pages (LibreOffice writes „<size> Tf“ in compressed
    streams), or infinity if none is found: then the copy is kept as it is."""
    sizes = collections.Counter()
    for stream in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf.read_bytes(), re.S):
        try:
            sizes.update(re.findall(rb"([\d.]+) Tf\b", zlib.decompress(stream.group(1))))
        except zlib.error:
            continue
    return float(sizes.most_common(1)[0][0]) if sizes else math.inf


def make_preview(document):
    """Store a PDF copy of a Word/Excel/PowerPoint/text/CSV document. Returns it or None."""
    extension = document.file_extension.lower()
    program = soffice()
    if extension not in CONVERTIBLE or program is None:
        return None
    with tempfile.TemporaryDirectory(prefix="infohub-preview-") as folder:
        folder = Path(folder)
        source = folder / f"file.{extension}"
        with document.file.open("rb") as original, source.open("wb") as copy:
            shutil.copyfileobj(original, copy)
        if not source.stat().st_size:
            return None  # nothing to show
        base = [
            program, f"-env:UserInstallation={(folder / 'profile').as_uri()}",  # own profile: runs in parallel
            "--headless", "--norestore", *_input_filter(source, extension),
        ]
        pdf = folder / "file.pdf"
        deadline = time.monotonic() + TIMEOUT_SECONDS
        try:
            if extension in SPREADSHEETS:
                _convert(base, WHOLE_SHEETS, source, deadline)
                if pdf.is_file() and _text_size(pdf) < READABLE_TEXT_PT:
                    pdf.unlink()
                    _convert(base, "pdf", source, deadline)
            else:
                _convert(base, "pdf", source, deadline)
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.warning("No PDF copy of document %s: %s", document.pk, error)
            return None
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
