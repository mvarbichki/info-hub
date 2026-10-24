"""The site's JavaScript in jsdom: the post editor, the „Кой да я вижда“ picker and the „Нов потребител“
form. The pages are rendered here from the test database, then tests/js/*.test.js runs on them.

Needs Node.js and, once, `npm install` in tests/js (skipped otherwise)."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from guides.models import GuidePage
from venues.models import Venue

from .base import InfoHubTestCase, png

JS_TESTS = Path(__file__).resolve().parent / "js"
STATIC = Path(settings.PROJECT_DIR) / "static"
NODE = shutil.which("node")


@skipUnless(NODE and (JS_TESTS / "node_modules" / "jsdom").is_dir(), "needs Node.js and `npm install` in tests/js")
class BrowserScriptTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.pages = Path(tempfile.mkdtemp(prefix="infohub-js-"))
        self.addCleanup(shutil.rmtree, self.pages, ignore_errors=True)

    def save(self, name, response):
        self.assertEqual(response.status_code, 200, name)
        (self.pages / name).write_text(response.content.decode(), encoding="utf-8")

    def run_node(self, script):
        result = subprocess.run(
            [NODE, str(JS_TESTS / script), str(STATIC), str(self.pages)],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
        failures = [line for line in result.stdout.splitlines() if line.startswith("FAIL")]
        self.assertEqual(result.returncode, 0, "\n".join(failures) or result.stdout[-2000:] + result.stderr[-2000:])
        return result.stdout.strip().splitlines()[-1]

    def test_editor_and_picker(self):
        client = self.client_for(self.admin)
        upload = lambda file, kind: self.upload(client, file, kind, place=self.it.pk)[1]["item"]
        pictures = [upload(png(color=c), "image") for c in ("red", "blue", "green")]
        video = upload(SimpleUploadedFile("v.mp4", b"x" * 2000), "video")
        pdf = upload(SimpleUploadedFile("f.pdf", b"%PDF"), "file")
        body = [
            {"type": "step", "title": "Стъпка А", "html": "<p>Текст <b>удебелен</b></p><ol><li>едно</li></ol>", "images": pictures[:2]},
            {"type": "step", "title": "Стъпка Б", "html": "", "images": []},
            {"type": "heading", "text": "Раздел"},
            {"type": "step", "title": "Стъпка В", "html": "<p>x</p>", "images": []},
            {"type": "text", "html": "<p>Обикновен <i>текст</i> <a href='https://example.com'>връзка</a></p><ul><li>т1</li></ul>"},
            {"type": "image", "image": pictures[2], "caption": "Надпис"},
            {"type": "video", "document": video, "caption": "Видео"},
            {"type": "note", "style": "tip", "html": "<p>Съвет!</p>"},
            {"type": "file", "document": pdf, "title": "Изтегли"},
        ]
        response = client.post("/manage/new/", {"title": "Тест", "summary": "", "place": self.it.pk, "kind": "guide",
                                                "body": json.dumps(body), "manager_venues": [self.sah.pk]})
        self.assertEqual(response.status_code, 302)
        guide = GuidePage.objects.get(title="Тест")
        self.save("edit.html", client.get(f"/manage/{guide.pk}/"))
        self.save("new.html", client.get("/manage/new/"))
        print("\n  editor.test.js:", self.run_node("editor.test.js"))

    def test_new_user_form(self):
        Venue.objects.create(name="София – Цариградско шосе")
        client = self.client_for(self.admin)
        self.save("users.html", client.get("/manage/users/"))
        self.save("users_new.html", client.get(f"/manage/users/?new_role=staff&new_venue={self.pernik.pk}"))
        self.save("users_error.html", client.post("/manage/users/", {"role": "editor", "username": "", "department": "", "password": "", "venue": ""}))
        print("\n  users.test.js:", self.run_node("users.test.js"))
