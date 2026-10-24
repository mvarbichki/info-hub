"""Shared test setup: the departments and editors of setup_infohub, two venues with their accounts,
helpers to log in, upload and save posts. Every test runs on a separate, empty test database and a
temporary media folder, so the real venues and accounts are never touched."""

import io
import json
import re
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from PIL import Image as PILImage

from dashboard.models import set_must_change_password
from guides.models import DepartmentPage, GuidePage
from venues.access import create_account
from venues.models import MANAGER, STAFF, Venue

PASSWORD = "Kasa-Tsvete-2026"
MEDIA_ROOT = tempfile.mkdtemp(prefix="infohub-test-media-")
EDITOR_CONFIG = re.compile(r'<script id="editor-config" type="application/json">(.*?)</script>', re.S)


def png(width=300, height=200, color="red", name="snimka.png", image_format="PNG"):
    buffer = io.BytesIO()
    PILImage.new("RGB", (width, height), color).save(buffer, image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@override_settings(
    MEDIA_ROOT=MEDIA_ROOT,
    ALLOWED_HOSTS=["testserver"],
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],  # fast; real hashing is Django's job
)
class InfoHubTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        call_command("setup_infohub", stdout=io.StringIO())
        User = get_user_model()
        cls.admin = User.objects.create_superuser("admin", "", "Admin-pass-2026")
        cls.marketing_editor = User.objects.get(username="marketing")
        cls.cms_editor = User.objects.get(username="cms")
        for editor in (cls.marketing_editor, cls.cms_editor):
            editor.set_password(f"{editor.username}-Pass-2026")
            editor.save()
            set_must_change_password(editor, False)
        cls.it = DepartmentPage.objects.get(slug="it")
        cls.marketing = DepartmentPage.objects.get(slug="marketing")
        cls.cms = DepartmentPage.objects.get(slug="cms")

        cls.training = Venue.objects.get(is_training=True)
        cls.training_staff = cls.training.accounts.get(role=STAFF).user
        cls.training_staff.set_password(PASSWORD)
        cls.training_staff.save()
        cls.pernik = Venue.objects.create(name="Перник")
        cls.sah = Venue.objects.create(name="София – Младост")
        cls.pernik_staff = create_account("pernik_staff", cls.pernik, STAFF, PASSWORD)
        cls.pernik_manager = create_account("pernik_manager", cls.pernik, MANAGER, PASSWORD)
        cls.mladost_staff = create_account("mladost_staff", cls.sah, STAFF, PASSWORD)
        cls.mladost_manager = create_account("mladost_manager", cls.sah, MANAGER, PASSWORD)

    def setUp(self):
        cache.clear()  # the login throttle

    # --- helpers -----------------------------------------------------------------------------

    def client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    def post_data(self, **changes):
        """The editor form of a simple post for all venues; None removes a field."""
        data = {
            "title": "Пост", "summary": "", "place": self.marketing.pk, "kind": "news",
            "body": json.dumps([{"type": "text", "html": "<p>текст</p>"}]), "all_venues": "on",
        }
        data.update(changes)
        return {key: value for key, value in data.items() if value is not None}

    def save_post(self, client, url="/manage/new/", **changes):
        """Post the editor form; returns (response, the post with that title or None)."""
        data = self.post_data(**changes)
        response = client.post(url, data)
        return response, GuidePage.objects.filter(draft_title=data["title"]).first()

    def upload(self, client, file, kind, place=None):
        response = client.post("/manage/upload/", {"file": file, "kind": kind, "place": place or self.marketing.pk})
        return response.status_code, response.json()

    @staticmethod
    def editor_config(response):
        return json.loads(EDITOR_CONFIG.search(response.content.decode()).group(1))

    @staticmethod
    def html(response):
        return response.content.decode()
