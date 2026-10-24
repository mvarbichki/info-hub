"""Server settings: error log, error pages, database check, setup command."""

import importlib
import io
import logging
import logging.config
import os
import re
import shutil
import sys
import tempfile
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client, SimpleTestCase, TransactionTestCase

from home.checks import mariadb_charset

from .base import InfoHubTestCase


def production_settings(**env):
    with mock.patch.dict(os.environ, {"DJANGO_SECRET_KEY": "x" * 50, **env}):
        sys.modules.pop("infohub.settings.production", None)
        return importlib.import_module("infohub.settings.production")


class ErrorLogTests(SimpleTestCase):
    def tearDown(self):
        sys.modules.pop("infohub.settings.production", None)

    def test_without_a_log_file_errors_go_to_the_console(self):
        settings = production_settings()
        self.assertEqual(set(settings.LOGGING["handlers"]), {"console"})
        self.assertEqual(settings.LOGGING["loggers"]["django.request"]["level"], "ERROR")  # no "Not Found" noise

    def test_errors_with_traceback_go_to_the_file(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "errors.log")
        settings = production_settings(INFOHUB_LOG_FILE=path)
        root = logging.getLogger()
        saved = root.handlers[:], root.level
        request_level = logging.getLogger("django.request").level
        with mock.patch("sys.stderr", io.StringIO()):  # the console handler writes there too
            logging.config.dictConfig(settings.LOGGING)
        try:
            try:
                raise ValueError("пример")
            except ValueError:
                logging.getLogger("django.request").error("Internal Server Error: /it/x/", exc_info=True)
            logging.getLogger("django.request").warning("Not Found: /wp-login.php")
        finally:
            for handler in root.handlers:
                handler.close()
            root.handlers[:], root.level = saved
            logging.getLogger("django.request").setLevel(request_level)
        text = open(path, encoding="utf-8").read()
        self.assertIn("Internal Server Error: /it/x/", text)
        self.assertIn("ValueError: пример", text)
        self.assertNotIn("wp-login", text)

    def test_production_is_secure_over_https(self):
        settings = production_settings()
        self.assertTrue(settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE)
        self.assertFalse(settings.DEBUG)


class PagesTests(SimpleTestCase):
    def test_server_error_page_says_when(self):
        html = render_to_string("500.html")
        self.assertRegex(html, r"\d{1,2}\.\d{2}\.\d{4} \d{2}:\d{2}")
        self.assertIn("записана", html)


class DatabaseCheckTests(InfoHubTestCase):
    def test_sqlite_is_not_checked(self):
        self.assertEqual(mariadb_charset(None, databases=["default"]), [])

    def test_wrong_mariadb_charset_is_reported(self):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value.fetchone.return_value = ("latin1", "latin1_swedish_ci")
        fake = mock.MagicMock(vendor="mysql", settings_dict={"NAME": "infohub", "OPTIONS": {"collation": "utf8mb4_unicode_ci"}})
        fake.cursor.return_value = cursor
        with mock.patch("home.checks.connections", {"default": fake}):
            errors = mariadb_charset(None, databases=["default"])
        self.assertEqual([e.id for e in errors], ["infohub.E001"])
        self.assertIn("ALTER DATABASE `infohub` CHARACTER SET utf8mb4", errors[0].hint)
        self.assertEqual(connection.vendor, "sqlite")


class SetupCommandTests(InfoHubTestCase):
    def test_setup_can_run_again_and_keeps_everything(self):
        out = io.StringIO()
        call_command("setup_infohub", stdout=out)
        self.assertIn("Вече съществува", out.getvalue())
        self.assertTrue(self.pernik_staff.check_password("Kasa-Tsvete-2026"))
        self.assertRegex(out.getvalue(), re.compile(r"обект „Обучение“ \(staff, manager\)|обект „Обучение“ \(manager, staff\)"))

    def test_add_department_command(self):
        out = io.StringIO()
        call_command("add_department", "Финанси", "finance", stdout=out)
        self.assertIn("Създаден", out.getvalue())


class MoveSiteTests(TransactionTestCase):
    """export_site → import_site carries everything to a new database (tested on MariaDB by hand too)."""

    def test_round_trip(self):
        from django.contrib.auth import get_user_model
        from django.core.management.base import CommandError

        from guides.models import DepartmentPage, GuidePage
        from stats.models import SearchStat
        from venues.access import create_account
        from venues.models import Venue

        call_command("setup_infohub", stdout=io.StringIO())
        venue = Venue.objects.create(name="Перник")
        create_account("pernik_staff", venue, "staff", "Kasa-Tsvete-2026")
        admin = get_user_model().objects.create_superuser("admin", "", "Admin-pass-2026")
        client = self.client
        client.force_login(admin)
        it = DepartmentPage.objects.get(slug="it")
        client.post("/manage/new/", {"title": "Пост", "summary": "", "place": it.pk, "kind": "news", "body": "[]", "staff_venues": [venue.pk]})
        SearchStat.objects.create(query="принтер", venue=venue, role="staff", day="2026-10-01", count=3)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "site.json")
        call_command("export_site", path, stdout=io.StringIO())

        with self.assertRaises(CommandError):
            call_command("import_site", path)  # without --yes nothing happens
        Venue.objects.all().delete()
        get_user_model().objects.filter(username="pernik_staff").delete()
        out = io.StringIO()
        call_command("import_site", path, "--yes", stdout=out)
        self.assertIn("Заредено", out.getvalue())
        post = GuidePage.objects.get(title="Пост")
        self.assertEqual(list(post.venues.values_list("name", flat=True)), ["Перник"])
        self.assertTrue(get_user_model().objects.get(username="pernik_staff").check_password("Kasa-Tsvete-2026"))
        self.assertTrue(SearchStat.objects.filter(query="принтер").exists())
        staff = Client()
        staff.post("/login/", {"username": "pernik_staff", "password": "Kasa-Tsvete-2026"})
        self.assertEqual(staff.get(post.url).status_code, 200)
