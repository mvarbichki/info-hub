"""manage.py check_site: OK on a healthy site, and it notices what can go wrong on a server."""

import datetime
import io
import json
import os
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from wagtail.documents.models import Document
from wagtail.images.models import Image
from wagtail.models import Collection, Page, Site

from dashboard.access import editor_groups
from dashboard.models import set_must_change_password
from guides.departments import department_group
from guides.models import DepartmentMedia, GuidePage
from home.models import HomePage
from stats.models import Ack, Seen, Vote
from venues.access import VENUE_GROUP
from venues.models import Venue

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

    def test_it_notices_each_kind_of_problem(self):
        """Every check, each on its own broken copy of the data (rolled back after each)."""
        venue_group = Group.objects.get(name=VENUE_GROUP)
        guide = GuidePage.objects.get(pk=self.guide.pk)
        home = HomePage.objects.get()
        cases = {
            "е записан 2 пъти": lambda: Venue.objects.create(name="перник"),
            "точно един обект за обучение": lambda: Venue.objects.create(name="Обучение 2", is_training=True),
            f"групата „{VENUE_GROUP}“ има права": lambda: venue_group.permissions.add(Permission.objects.first()),
            f"групата „{VENUE_GROUP}“ липсва": lambda: Group.objects.get(name=VENUE_GROUP).delete(),
            "pernik_staff: не е в групата": lambda: self.pernik_staff.groups.clear(),
            "marketing: редактор в групата на обектите": lambda: self.marketing_editor.groups.add(venue_group),
            "нито обект, нито редактор, нито администратор": lambda: User.objects.create_user("някой"),
            "трябва да смени паролата си": lambda: set_must_change_password(self.pernik_staff, True),
            "Seen: записи от потребител, който не е обект": lambda: Seen.objects.create(guide=guide, user=self.admin),
            "Ack: записи от потребител, който не е обект": lambda: Ack.objects.create(guide=guide, user=self.admin),
            "отговор „Да“ с причина": lambda: Vote.objects.create(
                guide=guide, user=self.pernik_manager, helpful=True, reason="защо", day=datetime.date.today()),
            "адресът /login/ е запазен": lambda: Page.objects.filter(pk=self.it.pk).update(slug="login"),
            "няма група редактори": lambda: department_group(self.it).delete(),
            "има достъп до /admin/": lambda: department_group(self.it).permissions.add(
                Permission.objects.get(codename="access_admin")),
            "няма папка за файлове": lambda: DepartmentMedia.objects.filter(department=self.it).delete(),
            "не е раздел": lambda: home.add_child(instance=Page(title="Случайна", slug="sluchayna")),
            "трябва по една, свързани": lambda: Site.objects.create(hostname="other", port=81, root_page=home),
            "не е в папката на раздела": lambda: Image.objects.update(collection=Collection.get_first_root_node()),
            "uploaded_media не съдържа": lambda: GuidePage.objects.filter(pk=guide.pk).update(uploaded_media={}),
        }
        for message, breaks in cases.items():
            with self.subTest(message), transaction.atomic():
                breaks()
                ok, output = self.run_check()
                self.assertFalse(ok, output)
                self.assertIn(message, output)
                transaction.set_rollback(True)

    def test_it_compares_who_sees_what_with_its_own_rule(self):
        everything = GuidePage.objects.all()
        nothing = GuidePage.objects.none()
        cases = [
            ("mladost_staff вижда публикация", {"visible_guides": lambda user: everything}),
            ("pernik_manager не вижда публикация", {"visible_guides": lambda user: nothing}),
            ("pernik_manager: не може да отвори файловете", {"visible_media": lambda user: (set(), set())}),
            ("mladost_staff: може да отвори файлове на публикации, които не са за него",
             {"visible_media": lambda user: (set(Image.objects.values_list("pk", flat=True)), set())}),
        ]
        for message, fakes in cases:
            with self.subTest(message), mock.patch.multiple("guides.management.commands.check_site", **fakes):
                ok, output = self.run_check()
                self.assertFalse(ok, output)
                self.assertIn(message, output)

    def test_a_file_without_its_pdf_copy_is_noted(self):
        word = self.upload(self.editor, SimpleUploadedFile("Бланка.docx", b"PK"), "file")[1]["item"]  # no LibreOffice
        ok, output = self.run_check()
        self.assertTrue(ok, output)
        self.assertIn("без PDF копие: Бланка (manage.py make_previews)", output)
        Document.objects.filter(pk=word["id"]).delete()
        self.upload(self.editor, SimpleUploadedFile("празен.docx", b""), "file")  # empty: never gets a copy
        self.assertNotIn("без PDF копие", self.run_check()[1])
