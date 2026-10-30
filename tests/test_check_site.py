"""manage.py check_site: OK on a healthy site, and it notices what can go wrong on a server."""

import io
import json
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from wagtail.documents.models import Document

from dashboard.access import editor_groups
from guides.models import GuidePage

from .base import InfoHubTestCase, png


class CheckSiteTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        picture = self.upload(self.editor, png(), "image")[1]["item"]
        self.pdf = self.upload(self.editor, SimpleUploadedFile("Правила.pdf", b"%PDF-1.4"), "file")[1]["item"]
        body = [{"type": "step", "title": "Стъпка", "html": "", "images": [picture], "files": [self.pdf]}]
        _, self.guide = self.save_post(self.editor, title="За Перник", all_venues=None, manager_venues=[self.pernik.pk],
                                       body=json.dumps(body))

    def run_check(self):
        out = io.StringIO()
        try:
            call_command("check_site", stdout=out)
        except CommandError as error:
            return False, out.getvalue() + str(error)
        return True, out.getvalue()

    def test_a_healthy_site_is_ok(self):
        ok, output = self.run_check()
        self.assertTrue(ok, output)
        self.assertIn("OK: няма проблеми.", output)
        self.assertIn("публикации: {'на сайта': 1}", output)

    def test_changes_nothing(self):
        before = GuidePage.objects.get(pk=self.guide.pk).latest_revision_id
        self.run_check()
        self.assertEqual(GuidePage.objects.get(pk=self.guide.pk).latest_revision_id, before)

    def test_a_missing_file(self):
        os.remove(Document.objects.get(pk=self.pdf["id"]).file.path)
        ok, output = self.run_check()
        self.assertFalse(ok)
        self.assertIn("файлът липсва на диска", output)

    def test_a_venue_account_with_editor_rights(self):
        self.pernik_staff.groups.add(editor_groups().first())
        ok, output = self.run_check()
        self.assertFalse(ok)
        self.assertIn("pernik_staff: акаунт на обект с права на редактор/администратор", output)

    def test_wrong_visibility(self):
        # A post stored as "for everybody" with a venue list: the data no longer says one thing.
        GuidePage.objects.filter(pk=self.guide.pk).update(audience="all")
        ok, output = self.run_check()
        self.assertFalse(ok)
        self.assertIn("„Всички обекти“, но със списък обекти", output)

    def test_stale_search_text(self):
        GuidePage.objects.filter(pk=self.guide.pk).update(search_text="")
        ok, output = self.run_check()
        self.assertFalse(ok)
        self.assertIn("текстът за търсене е остарял", output)
