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
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client, SimpleTestCase, TransactionTestCase

from home.checks import mariadb_database
from infohub.envfile import load

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


class EnvFileTests(SimpleTestCase):
    """Shared hosting: passenger_wsgi.py and manage.py read the settings from .env."""

    def test_lines_are_read_and_the_real_environment_wins(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, ".env")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# comment\n\nINFOHUB_T_A=1\nexport INFOHUB_T_B = 'a b=c'\nINFOHUB_T_C=\"x\"\nnot a setting\nINFOHUB_T_D=new\n")
        with mock.patch.dict(os.environ, {"INFOHUB_T_D": "old"}):
            load(path)
            self.assertEqual([os.environ.get(f"INFOHUB_T_{k}") for k in "ABCD"], ["1", "a b=c", "x", "old"])
        load(os.path.join(folder, "missing.env"))  # no file: nothing happens

    def test_static_root_can_be_moved(self):
        with mock.patch.dict(os.environ, {"INFOHUB_STATIC_ROOT": "/home/u/site/static"}):
            sys.modules.pop("infohub.settings.base", None)
            try:
                self.assertEqual(str(importlib.import_module("infohub.settings.base").STATIC_ROOT), str(Path("/home/u/site/static")))
            finally:
                sys.modules.pop("infohub.settings.base", None)


class DatabaseCheckTests(InfoHubTestCase):
    def check(self, charset, tables):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value.fetchone.return_value = charset
        cursor.__enter__.return_value.fetchall.return_value = [(t,) for t in tables]
        fake = mock.MagicMock(vendor="mysql", settings_dict={"NAME": "infohub", "OPTIONS": {"collation": "utf8mb4_unicode_ci"}})
        fake.cursor.return_value = cursor
        with mock.patch("home.checks.connections", {"default": fake}):
            return mariadb_database(None, databases=["default"])

    def test_sqlite_is_not_checked(self):
        self.assertEqual(connection.vendor, "sqlite")
        self.assertEqual(mariadb_database(None, databases=["default"]), [])

    def test_right_mariadb_database_passes(self):
        self.assertEqual(self.check(("utf8mb4", "utf8mb4_unicode_ci"), []), [])

    def test_wrong_mariadb_charset_is_reported(self):
        errors = self.check(("latin1", "latin1_swedish_ci"), [])
        self.assertEqual([e.id for e in errors], ["infohub.E001"])
        self.assertIn("ALTER DATABASE `infohub` CHARACTER SET utf8mb4", errors[0].hint)

    def test_myisam_tables_are_reported(self):
        errors = self.check(("utf8mb4", "utf8mb4_unicode_ci"), ["wagtailcore_page", "auth_user"])
        self.assertEqual([e.id for e in errors], ["infohub.E002"])
        self.assertIn("2 tables", errors[0].msg)
        self.assertIn("Drop", errors[0].hint)

    def test_mariadb_connection_asks_for_innodb(self):
        with mock.patch.dict(os.environ, {"MARIADB_DB": "x"}), mock.patch.dict(sys.modules, {"MySQLdb": mock.MagicMock()}):
            sys.modules.pop("infohub.settings.base", None)
            try:
                options = importlib.import_module("infohub.settings.base").DATABASES["default"]["OPTIONS"]
            finally:
                sys.modules.pop("infohub.settings.base", None)
        self.assertIn("default_storage_engine=INNODB", options["init_command"])

    def test_postgres_switches_on_its_app(self):
        # Docker: without django.contrib.postgres the web container stops at postgres.E005.
        with mock.patch.dict(os.environ, {"POSTGRES_DB": "x"}):
            sys.modules.pop("infohub.settings.base", None)
            try:
                settings = importlib.import_module("infohub.settings.base")
            finally:
                sys.modules.pop("infohub.settings.base", None)
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")
        self.assertIn("django.contrib.postgres", settings.INSTALLED_APPS)


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
        with open(path, encoding="utf-8") as f:
            self.assertIn("Перник", f.read())  # UTF-8 whatever the system code page (Windows: cp1251/1252)

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


class DownPageTests(SimpleTestCase):
    """nginx's page while the app restarts or is down (deploy/maintenance, nginx.conf, docker-compose.yml)."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_nginx_shows_them(self):
        conf = (self.ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("error_page 502 503 504 $down_page;", conf)
        self.assertRegex(conf, r"POST\s+/maintenance-form\.html;")
        self.assertRegex(conf, r"default\s+/maintenance\.html;")
        self.assertIn("root /usr/share/nginx/infohub;", conf)
        self.assertIn("internal;", conf.split("location ~ ^/maintenance")[1].split("}")[0])
        compose = (self.ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("./deploy/maintenance:/usr/share/nginx/infohub:ro", compose)

    def test_the_pages(self):
        folder = self.ROOT / "deploy" / "maintenance"
        page = (folder / "maintenance.html").read_text(encoding="utf-8")
        form = (folder / "maintenance-form.html").read_text(encoding="utf-8")
        for html in (page, form):
            self.assertIn('<html lang="bg">', html)
            self.assertIn('<meta charset="utf-8">', html)
            self.assertNotRegex(html, r'(src|href)="(https?:)?//')  # nothing from elsewhere: the app may be down
            self.assertNotRegex(html, r"\{[{%]")  # plain files, not templates
        self.assertIn('http-equiv="refresh" content="15"', page)
        self.assertNotIn("refresh", form)  # a reload would lose what was typed
        self.assertIn("Назад", form)


class LoginPageHelpersTests(InfoHubTestCase):
    def test_show_password_and_caps_lock(self):
        html = Client().get("/login/").content.decode()
        self.assertIn('id="id_password"', html)
        self.assertIn('<label for="id_password">Парола</label>', html)
        self.assertRegex(html, r"data-password-toggle[^>]*hidden>Покажи</button>")  # shown by the script
        self.assertRegex(html, r"data-caps-warning[^>]*hidden>Caps Lock е включен")
        self.assertEqual(Client().post("/login/", {"username": "pernik_staff", "password": "Kasa-Tsvete-2026"}).status_code, 302)

