"""Content-Security-Policy (2026-11-03): only the site's own script files run, on every page."""

import re

from django.test import Client
from wagtail.images.models import Image

from .base import InfoHubTestCase, png

INLINE_HANDLER = re.compile(r"<[^>]+\son[a-z]+\s*=", re.I)
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\ssrc=)(?![^>]*type=\"application/json\")[^>]*>", re.I)


class SecurityPolicyTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.picture = self.upload(self.editor, png(), "image")[1]["item"]
        _, self.post = self.save_post(self.editor, title="Принтер", needs_ack="on", body=(
            '[{"type": "image", "image": {"id": %d}}, {"type": "text", "html": "<p>текст</p>"}]' % self.picture["id"]
        ))

    def pages(self):
        boss = self.client_for(self.admin)
        venue = self.client_for(self.pernik_manager)
        yield Client(), "/login/"
        for client in (venue, self.editor):
            for url in ("/", "/marketing/", "/search/?q=принтер", self.post.url, "/no-such-page/"):
                yield client, url
        for url in ("/manage/", "/manage/new/", f"/manage/{self.post.pk}/", "/manage/stats/", "/manage/categories/",
                    f"/manage/{self.post.pk}/reads/", f"/manage/{self.post.pk}/history/", "/manage/activity/",
                    "/manage/view-as/", "/manage/password/"):
            yield self.editor, url
        for url in ("/manage/users/", "/manage/venues/", "/manage/departments/", "/manage/settings/"):
            yield boss, url

    def test_every_page_has_the_policy_and_no_inline_scripts(self):
        for client, url in self.pages():
            with self.subTest(url=url):
                response = client.get(url)
                self.assertIn(response.status_code, (200, 404))
                policy = response["Content-Security-Policy"]
                self.assertIn("script-src 'self'", policy)
                self.assertIn("object-src 'none'", policy)
                self.assertIn("frame-ancestors 'self'", policy)
                self.assertNotIn("unsafe-inline", policy.split("script-src")[1].split(";")[0])
                html = response.content.decode()
                self.assertIsNone(INLINE_HANDLER.search(html), INLINE_HANDLER.search(html))
                self.assertIsNone(INLINE_SCRIPT.search(html), INLINE_SCRIPT.search(html))

    def test_the_password_sheet_too(self):
        boss = self.client_for(self.admin)
        page = boss.get("/manage/venues/").content.decode()
        token = re.search(r'name="sheet_token" value="([^"]+)"', page).group(1)
        response = boss.post(f"/manage/venues/{self.pernik.pk}/passwords/", {"sheet_token": token})
        self.assertEqual(response.status_code, 200)
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertIsNone(INLINE_HANDLER.search(response.content.decode()))

    def test_files_are_left_alone(self):
        image = Image.objects.get(pk=self.picture["id"])
        response = self.client_for(self.pernik_staff).get(image.file.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Security-Policy", response)
