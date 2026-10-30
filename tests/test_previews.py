"""Files inside a step, and the PDF copies of Word/Excel/PowerPoint files shown in the post."""

import io
import json
import os
from pathlib import Path
from unittest import mock, skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from wagtail.documents.models import Document

from guides.cleanup import stray_files
from guides.models import DocumentPreview, GuidePage
from guides.previews import soffice

from .base import InfoHubTestCase, png

FAKE_PDF = b"%PDF-1.4 fake copy"


def fake_libreoffice(command, **kwargs):
    """Writes file.pdf next to the source, like `soffice --convert-to pdf --outdir <folder>`."""
    folder = Path(command[command.index("--outdir") + 1])
    (folder / "file.pdf").write_bytes(FAKE_PDF)


def libreoffice_here():
    with override_settings(INFOHUB_SOFFICE=""):
        return soffice()


class StepFilesTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)
        self.picture = self.upload(self.editor, png(), "image")[1]["item"]
        self.form = self.upload(self.editor, SimpleUploadedFile("Бланка.xlsx", b"PK excel"), "file")[1]["item"]
        self.rules = self.upload(self.editor, SimpleUploadedFile("Правила.pdf", b"%PDF-1.4"), "file")[1]["item"]
        body = [{"type": "step", "title": "Попълнете бланката", "html": "<p>и я пратете</p>",
                 "images": [self.picture], "files": [self.form, self.rules]}]
        _, self.guide = self.save_post(self.editor, title="Заявка", body=json.dumps(body))

    def test_a_step_keeps_its_files_in_order(self):
        step = self.guide.body[0].value[0]
        self.assertEqual([d.pk for d in step["files"]], [self.form["id"], self.rules["id"]])
        self.assertEqual(sorted(self.guide.uploaded_media["documents"]), sorted([self.form["id"], self.rules["id"]]))
        blocks = self.editor_config(self.editor.get(f"/manage/{self.guide.pk}/"))["blocks"]
        self.assertEqual([f["id"] for f in blocks[0]["files"]], [self.form["id"], self.rules["id"]])

    def test_the_venue_sees_and_downloads_them(self):
        html = self.html(self.staff.get(self.guide.url))
        step = html.split('<ol class="steps">')[1].split("</ol>")[0]
        self.assertIn('class="step__files"', step)
        self.assertNotIn("{#", html)  # a template comment never shows on the page
        self.assertIn("Бланка", step)
        self.assertEqual(step.count("data-pdf-view="), 1)  # the PDF; the Excel file has no copy (LibreOffice off)
        for item in (self.form, self.rules):
            self.assertEqual(self.staff.get(Document.objects.get(pk=item["id"]).url).status_code, 200)

    def test_a_step_with_only_a_file_is_kept(self):
        body = [{"type": "step", "title": "", "html": "", "images": [], "files": [self.form]}]
        self.save_post(self.editor, url=f"/manage/{self.guide.pk}/", title="Заявка", body=json.dumps(body))
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.body[0].block_type, "steps")

    def test_someone_elses_file_is_refused(self):
        other = self.upload(self.client_for(self.cms_editor), SimpleUploadedFile("чужд.pdf", b"%PDF"), "file")[1]["item"]
        body = [{"type": "step", "title": "Стъпка", "html": "", "images": [], "files": [other]}]
        response, _ = self.save_post(self.editor, url=f"/manage/{self.guide.pk}/", title="Заявка", body=json.dumps(body))
        self.assertContains(response, "Един от файловете вече не съществува")

    def test_old_steps_without_files_still_work(self):
        stored = list(self.guide.body.raw_data)
        for step in stored[0]["value"]:
            step["value"].pop("files", None)
        GuidePage.objects.filter(pk=self.guide.pk).update(body=json.dumps(stored))
        self.assertEqual(self.staff.get(self.guide.url).status_code, 200)
        self.assertEqual(self.editor_config(self.editor.get(f"/manage/{self.guide.pk}/"))["blocks"][0]["files"], [])


@override_settings(INFOHUB_SOFFICE="soffice")
class PreviewTests(InfoHubTestCase):
    """Word/Excel/PowerPoint: a PDF copy on upload, shown in the post; the download is the original."""

    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        patcher = mock.patch("guides.previews.subprocess.run", side_effect=fake_libreoffice)
        self.run = patcher.start()
        self.addCleanup(patcher.stop)
        self.word = self.upload(self.editor, SimpleUploadedFile("Правилник.docx", b"PK word"), "file")[1]["item"]
        body = [{"type": "file", "document": self.word, "title": "Правилник"}]
        _, self.guide = self.save_post(self.editor, title="Правилник", all_venues=None, staff_venues=[self.pernik.pk],
                                       body=json.dumps(body))
        self.document = Document.objects.get(pk=self.word["id"])

    def test_a_copy_is_made_on_upload(self):
        preview = self.document.preview
        self.assertTrue(preview.file.name.startswith("previews/"))
        with preview.file.open("rb") as f:
            self.assertEqual(f.read(), FAKE_PDF)
        command = self.run.call_args.args[0]
        self.assertEqual(command[0], "soffice")
        self.assertIn("--headless", command)
        self.assertTrue(any(part.startswith("-env:UserInstallation=file:") for part in command))

    def test_the_post_shows_the_copy_and_downloads_the_original(self):
        html = self.html(self.client_for(self.pernik_staff).get(self.guide.url))
        self.assertIn(f'data-pdf-view="{self.document.preview.file.url}"', html)
        self.assertIn(f'href="{self.document.url}" download', html)

    def test_only_who_may_see_the_post_opens_the_copy(self):
        url = self.document.preview.file.url
        response = self.client_for(self.pernik_staff).get(url)
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "application/pdf"))
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(self.client_for(self.mladost_staff).get(url).status_code, 404)

    def test_no_copy_for_other_files_or_without_libreoffice(self):
        pdf = self.upload(self.editor, SimpleUploadedFile("a.pdf", b"%PDF"), "file")[1]["item"]
        text = self.upload(self.editor, SimpleUploadedFile("a.txt", b"x"), "file")[1]["item"]
        self.assertFalse(DocumentPreview.objects.filter(document_id__in=[pdf["id"], text["id"]]).exists())
        with override_settings(INFOHUB_SOFFICE="off"):
            excel = self.upload(self.editor, SimpleUploadedFile("t.xlsx", b"PK"), "file")[1]["item"]
        self.assertFalse(DocumentPreview.objects.filter(document_id=excel["id"]).exists())

    def test_a_failed_conversion_leaves_the_file_download_only(self):
        for failure in (lambda *a, **k: None, OSError("missing")):
            self.run.side_effect = failure
            status, answer = self.upload(self.editor, SimpleUploadedFile("счупен.docx", b"PK"), "file")
            self.assertEqual(status, 200)  # the upload itself works
            self.assertFalse(DocumentPreview.objects.filter(document_id=answer["item"]["id"]).exists())

    def test_the_copy_goes_with_the_file(self):
        path = self.document.preview.file.path
        with self.captureOnCommitCallbacks(execute=True):
            self.document.delete()
        self.assertFalse(DocumentPreview.objects.exists())
        self.assertFalse(os.path.exists(path))

    def test_cleanup_knows_the_copies(self):
        os.utime(self.document.preview.file.path, (0, 0))  # old enough to be cleaned if unknown
        self.assertNotIn(Path(self.document.preview.file.path), [Path(p) for p in stray_files()])

    def test_command_makes_missing_copies(self):
        DocumentPreview.objects.all().delete()
        out = io.StringIO()
        call_command("make_previews", stdout=out)
        self.assertIn("PDF копия: 1 от 1", out.getvalue())
        self.assertTrue(DocumentPreview.objects.filter(document=self.document).exists())
        with override_settings(INFOHUB_SOFFICE="off"):
            err = io.StringIO()
            call_command("make_previews", stdout=io.StringIO(), stderr=err)
            self.assertIn("Няма LibreOffice", err.getvalue())


@skipUnless(libreoffice_here(), "LibreOffice is not installed here (the Docker image has it)")
class RealLibreOfficeTests(InfoHubTestCase):
    """The real conversion, where LibreOffice is installed (this runs inside the Docker image too)."""

    def test_a_real_document_with_cyrillic_becomes_a_pdf(self):
        letters = "".join(f"\\u{ord(c)}?" for c in "Принтер")  # RTF writes a Unicode letter as \uNNNN?
        rtf = ("{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Arial;}}\\f0 " + letters + " test}").encode("ascii")
        with override_settings(INFOHUB_SOFFICE=libreoffice_here()):
            item = self.upload(self.client_for(self.marketing_editor), SimpleUploadedFile("пример.rtf", rtf), "file")[1]["item"]
        preview = DocumentPreview.objects.get(document_id=item["id"])
        with preview.file.open("rb") as f:
            self.assertEqual(f.read(5), b"%PDF-")
