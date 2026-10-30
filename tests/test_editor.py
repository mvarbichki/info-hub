"""The post editor: uploads, saving, cleaning, editing, errors, departments, archive, delete, cleanup."""

import io
import json
import os
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from PIL import Image as PILImage
from wagtail.documents.models import Document
from wagtail.images.models import Image

from guides.cleanup import unused_media
from guides.departments import department_collection
from guides.models import GuidePage
from stats.models import GuideStat

from .base import InfoHubTestCase, png

VIDEO = bytes(range(256)) * 400  # 102 400 bytes


class UploadTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)

    def test_picture_is_shrunk_and_filed_in_the_department(self):
        status, data = self.upload(self.editor, png(3000, 1000, name="Голяма снимка.png"), "image")
        self.assertEqual(status, 200)
        self.assertTrue(data["item"]["thumb"].startswith("/media/images/"))
        image = Image.objects.get(pk=data["item"]["id"])
        self.assertEqual(image.width, 2000)
        self.assertEqual(image.collection_id, department_collection(self.marketing).pk)
        self.assertEqual(image.uploaded_by_user, self.marketing_editor)

    def test_pictures_other_formats_and_broken_files(self):
        status, data = self.upload(self.editor, SimpleUploadedFile("x.png", b"not an image"), "image")
        self.assertEqual(status, 400)
        self.assertIn("не е снимка", data["error"])
        bmp = io.BytesIO()
        PILImage.new("RGB", (50, 50)).save(bmp, "BMP")
        status, data = self.upload(self.editor, SimpleUploadedFile("old.bmp", bmp.getvalue()), "image")
        self.assertEqual(status, 200)
        self.assertTrue(Image.objects.get(pk=data["item"]["id"]).file.name.endswith(".png"))

    def test_videos_and_files(self):
        status, data = self.upload(self.editor, SimpleUploadedFile("Обучение.mp4", VIDEO), "video")
        self.assertEqual((status, data["warning"]), (200, ""))
        self.assertTrue(data["item"]["name"].endswith(".mp4"))
        status, data = self.upload(self.editor, SimpleUploadedFile("iphone.mov", b"x" * 100), "video")
        self.assertEqual(status, 200)
        self.assertIn("MP4", data["warning"])
        self.assertEqual(self.upload(self.editor, SimpleUploadedFile("doc.pdf", b"x"), "video")[0], 400)
        self.assertEqual(self.upload(self.editor, SimpleUploadedFile("Правилник.pdf", b"%PDF-1.4"), "file")[0], 200)
        status, data = self.upload(self.editor, SimpleUploadedFile("virus.exe", b"MZ"), "file")
        self.assertEqual(status, 400)
        self.assertIn(".exe", data["error"])
        self.assertEqual(self.upload(self.editor, SimpleUploadedFile("noext", b"x"), "file")[0], 400)
        self.assertEqual(self.upload(self.editor, SimpleUploadedFile("a.png", b"x"), "other")[0], 400)
        self.assertEqual(self.editor.post("/manage/upload/", {"kind": "image"}).status_code, 400)

    @override_settings(INFOHUB_LIMITS_MB={"image": 0.00001, "video": 300, "file": 50})
    def test_too_big_file_is_refused_with_the_limit(self):
        status, data = self.upload(self.editor, png(), "image")
        self.assertEqual(status, 400)
        self.assertIn("максимумът", data["error"])

    def test_upload_aimed_at_another_department_lands_in_your_own(self):
        cms = self.client_for(self.cms_editor)
        status, data = self.upload(cms, png(), "image", place=self.marketing.pk)
        self.assertEqual(status, 200)
        self.assertEqual(Image.objects.get(pk=data["item"]["id"]).collection_id, department_collection(self.cms).pk)

    def test_upload_needs_post(self):
        self.assertEqual(self.editor.get("/manage/upload/").status_code, 405)


class SaveTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.pictures = [self.upload(self.editor, png(color=c), "image")[1]["item"] for c in ("red", "blue", "green", "yellow")]
        self.video = self.upload(self.editor, SimpleUploadedFile("Обучение.mp4", VIDEO), "video")[1]["item"]
        self.pdf = self.upload(self.editor, SimpleUploadedFile("Правилник.pdf", b"%PDF-1.4 test"), "file")[1]["item"]

    def full_body(self):
        p = self.pictures
        return [
            {"type": "step", "title": "Отворете  настройките", "html": "<p>Натиснете&nbsp;<strong>Старт</strong> <script>alert(1)</script><img src=x onerror=1></p>", "images": [p[0], p[1]]},
            {"type": "step", "title": "Изберете принтера", "html": "", "images": []},
            {"type": "text", "html": '<p>Обикновен <em>текст</em> с <a href="https://example.com" target="_blank">връзка</a> и <a href="javascript:alert(1)">лоша</a>.</p><ul><li>едно</li></ul>'},
            {"type": "text", "html": "<p><br></p>"},
            {"type": "heading", "text": "Ако проблемът остане"},
            {"type": "image", "image": p[2], "caption": "Екранът"},
            {"type": "video", "document": self.video, "caption": "Видео урок"},
            {"type": "note", "style": "warning", "html": "<p>Не изключвайте компютъра!</p>"},
            {"type": "note", "style": "evil", "html": "<p>Стил по подразбиране</p>"},
            {"type": "file", "document": self.pdf, "title": "Изтегли правилника"},
            {"type": "step", "title": "Обадете се на ИТ", "html": "<p>вътр. 123</p>", "images": [p[3]]},
            {"type": "bogus", "x": 1},
            "not a block",
        ]

    def save_full(self):
        response, guide = self.save_post(self.editor, title="  Принтерът   не печата ", summary="Какво да направите.",
                                         kind="guide", body=json.dumps(self.full_body()))
        return response, GuidePage.objects.get(title="Принтерът не печата")

    def test_new_post_is_stored_cleanly(self):
        response, guide = self.save_full()
        self.assertRedirects(response, "/manage/", fetch_redirect_response=False)
        self.assertEqual([b.block_type for b in guide.body], ["steps", "text", "heading", "image", "video", "note", "note", "file", "steps"])
        steps = guide.body[0].value
        self.assertEqual((len(steps), len(steps[0]["images"])), (2, 2))
        self.assertEqual(steps[0]["title"], "Отворете настройките")
        source = steps[0]["text"].source
        self.assertIn("<b>Старт</b>", source)
        for bad in ("script", "<img", "\xa0", "&nbsp;"):
            self.assertNotIn(bad, source)
        text = guide.body[1].value.source
        self.assertIn('href="https://example.com"', text)
        self.assertNotIn("javascript", text)
        self.assertIn("<i>текст</i>", text)
        self.assertEqual(guide.body[6].value["style"], "info")  # unknown style -> info
        self.assertEqual(sorted(guide.uploaded_media["images"]), sorted(p["id"] for p in self.pictures))
        self.assertEqual(sorted(guide.uploaded_media["documents"]), sorted([self.video["id"], self.pdf["id"]]))
        self.assertEqual(Image.objects.get(pk=self.pictures[1]["id"]).title, "Принтерът не печата – снимка 2")
        self.assertIn("старт", guide.search_text)
        self.assertTrue(guide.live)
        self.assertEqual(guide.slug, "printerat-ne-pechata")

    def test_staff_see_it_rendered(self):
        _, guide = self.save_full()
        html = self.html(self.client_for(self.pernik_staff).get(guide.url))
        self.assertIn("Отворете настройките", html)
        self.assertIn("step__images--grid", html)
        self.assertEqual(html.count("zoomable step__image"), 3)
        for part in ("<video", "Изтегли правилника", "note--warning", "Помогна ли ви"):
            self.assertIn(part, html)

    def test_same_title_gets_its_own_address(self):
        _, first = self.save_post(self.editor, title="Каса")
        _, second = self.save_post(self.editor, title="Каса", summary="втора")
        self.assertEqual({p.slug for p in GuidePage.objects.filter(title="Каса")}, {"kasa", "kasa-2"})

    def test_edit_keeps_address_and_deletes_removed_media(self):
        _, guide = self.save_full()
        blocks = self.editor_config(self.editor.get(f"/manage/{guide.pk}/"))["blocks"]
        self.assertEqual([b["type"] for b in blocks], ["step", "step", "text", "heading", "image", "video", "note", "note", "file", "step"])
        blocks[0]["images"] = [blocks[0]["images"][1]]  # drop the first picture
        del blocks[5]  # drop the video
        blocks[0]["title"] = "Нов текст"
        dropped_files = [Image.objects.get(pk=self.pictures[0]["id"]).file.path, Document.objects.get(pk=self.video["id"]).file.path]
        with self.captureOnCommitCallbacks(execute=True):
            response, _ = self.save_post(self.editor, url=f"/manage/{guide.pk}/", title="Принтерът не печата",
                                         summary="Ново описание.", kind="guide", body=json.dumps(blocks))
        self.assertEqual(response.status_code, 302)
        guide.refresh_from_db()
        self.assertEqual(guide.slug, "printerat-ne-pechata")
        self.assertEqual(guide.body[0].value[0]["title"], "Нов текст")
        self.assertFalse(Image.objects.filter(pk=self.pictures[0]["id"]).exists())
        self.assertFalse(Document.objects.filter(pk=self.video["id"]).exists())
        for path in dropped_files:
            self.assertFalse(os.path.exists(path), path)
        self.assertTrue(Image.objects.filter(pk=self.pictures[1]["id"]).exists())

    def test_delete_removes_the_post_and_its_media(self):
        _, guide = self.save_full()
        media = guide.uploaded_media
        response = self.editor.post(f"/manage/{guide.pk}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(GuidePage.objects.filter(pk=guide.pk).exists())
        self.assertFalse(Image.objects.filter(pk__in=media["images"]).exists())
        self.assertFalse(Document.objects.filter(pk__in=media["documents"]).exists())

    def test_cleanup_removes_abandoned_uploads_only(self):
        _, guide = self.save_post(self.editor, title="С една снимка", body=json.dumps([{"type": "image", "image": self.pictures[0]}]))
        old = timezone.now() - timedelta(days=2)
        Image.objects.update(created_at=old)
        Document.objects.update(created_at=old)
        images, documents = unused_media()
        unused = {i.pk for i in images}
        self.assertNotIn(self.pictures[0]["id"], unused)
        self.assertIn(self.pictures[1]["id"], unused)
        self.assertEqual({d.pk for d in documents}, {self.video["id"], self.pdf["id"]})
        call_command("cleanup_media", "--dry-run", stdout=io.StringIO())
        self.assertTrue(Image.objects.filter(pk=self.pictures[1]["id"]).exists())
        call_command("cleanup_media", stdout=io.StringIO())
        self.assertFalse(Image.objects.filter(pk=self.pictures[1]["id"]).exists())
        self.assertTrue(Image.objects.filter(pk=self.pictures[0]["id"]).exists())

    def test_cleanup_removes_files_without_a_record(self):
        from django.conf import settings

        folder = os.path.join(settings.MEDIA_ROOT, "original_images")
        os.makedirs(folder, exist_ok=True)
        stray, fresh = os.path.join(folder, "stray.png"), os.path.join(folder, "fresh.png")
        for path in (stray, fresh):
            with open(path, "wb") as f:
                f.write(b"x")
        old = (timezone.now() - timedelta(days=2)).timestamp()
        os.utime(stray, (old, old))
        out = io.StringIO()
        call_command("cleanup_media", stdout=out)
        self.assertFalse(os.path.exists(stray))
        self.assertTrue(os.path.exists(fresh))  # may belong to an upload in progress
        self.assertTrue(Image.objects.filter(pk=self.pictures[0]["id"]).exists())

    def test_fresh_upload_is_not_cleaned_yet(self):
        images, _ = unused_media()
        self.assertEqual(images, [])


class EditorErrorTests(InfoHubTestCase):
    """Every failure says what is wrong, next to its part of the page, and nothing is saved."""

    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.boss = self.client_for(self.admin)

    def section_of(self, html, text):
        """Which part of the editor page shows `text`: main / content / audience."""
        i = html.find(text)
        self.assertGreaterEqual(i, 0, f"„{text}“ not on the page")
        part = "main"
        for heading, name in (("<h2>Съдържание</h2>", "content"), ("<h2>Кой да я вижда</h2>", "audience")):
            if 0 <= html.find(heading) < i:
                part = name
        return part

    def assertRefused(self, response, message, where):
        html = self.html(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn("не е запазена", html)
        self.assertEqual(self.section_of(html, message), where, message)

    def test_each_error_in_its_place(self):
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        cases = [
            (self.editor, {"title": "   "}, "Въведете заглавие.", "main"),
            (self.editor, {"title": "а" * 256}, "Заглавието е твърде дълго: до 255 знака (сега 256).", "main"),
            (self.editor, {"summary": "б" * 301}, "Краткото описание е до 300 знака (сега 301). Съкратете го.", "main"),
            (self.editor, {"place": self.cms.pk}, "Това място вече не съществува или нямате достъп до него.", "main"),
            (self.editor, {"place": None}, "Изберете къде да се публикува.", "main"),
            (self.editor, {"kind": "xyz"}, "Изберете вид: ръководство, новина или кампания.", "main"),
            (self.boss, {"is_pinned": "on", "pinned_until": yesterday}, "Тази дата е минала.", "main"),
            (self.boss, {"is_pinned": "on", "pinned_until": "31.31.2026"}, "Въведете дата, напр. 31.12.2026.", "main"),
            (self.editor, {"all_venues": None}, "Изберете кой да вижда публикацията", "audience"),
            (self.editor, {"all_venues": None, "staff_venues": [self.pernik.pk], "manager_venues": [self.sah.pk]}, "не двете заедно", "audience"),
            (self.editor, {"all_venues": None, "staff_venues": [999999]}, "Един от избраните обекти вече не съществува (изтрит е).", "audience"),
            (self.editor, {"body": "{oops"}, "Съдържанието не можа да бъде прочетено.", "content"),
            (self.editor, {"body": '{"type": "text"}'}, "Съдържанието не можа да бъде прочетено.", "content"),
            (self.editor, {"body": json.dumps([{"type": "heading", "text": "x"}] * 301)}, "Публикацията има над 300 блока.", "content"),
            (self.editor, {"body": json.dumps([{"type": "image", "image": {"id": 999999}}])}, "Една от снимките вече не съществува.", "content"),
            (self.editor, {"body": json.dumps([{"type": "file", "document": {"id": 999999}}])}, "Един от файловете вече не съществува.", "content"),
        ]
        for client, changes, message, where in cases:
            with self.subTest(message=message):
                response, _ = self.save_post(client, **{"title": "Грешна", **changes})
                self.assertRefused(response, message, where)
        self.assertFalse(GuidePage.objects.exists())

    def test_deleted_venue_gives_one_clear_message(self):
        response, _ = self.save_post(self.editor, all_venues=None, staff_venues=[999999])
        self.assertNotContains(response, "Изберете кой да вижда")

    def test_a_pdf_is_not_a_video(self):
        pdf = self.upload(self.editor, SimpleUploadedFile("a.pdf", b"%PDF"), "file")[1]["item"]
        response, _ = self.save_post(self.editor, body=json.dumps([{"type": "video", "document": pdf}]))
        self.assertRefused(response, "не е видео", "content")

    def test_what_was_typed_stays_after_an_error(self):
        response, _ = self.save_post(self.editor, title="Запази ме", all_venues=None,
                                     body=json.dumps([{"type": "heading", "text": "Остани"}]))
        self.assertContains(response, 'value="Запази ме"')
        self.assertEqual(self.editor_config(response)["blocks"], [{"type": "heading", "text": "Остани"}])

    def test_a_post_with_only_a_title_is_allowed(self):
        response, guide = self.save_post(self.editor, title="Само заглавие", body="[]")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(guide.body), [])


class DepartmentRulesTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.cms_client = self.client_for(self.cms_editor)

    def test_editor_page_offers_only_own_places_and_no_pin(self):
        html = self.html(self.editor.get(f"/manage/new/?place={self.marketing.pk}"))
        self.assertIn(f'<option value="{self.marketing.pk}" selected', html)
        self.assertNotIn("Казино", html.split('name="place"')[1].split("</select>")[0])
        self.assertNotIn("is_pinned", html)
        self.assertIn("is_pinned", self.html(self.client_for(self.admin).get("/manage/new/")))

    def test_departments_cannot_touch_each_others_posts_or_pictures(self):
        _, guide = self.save_post(self.editor, title="Маркетингова")
        picture = self.upload(self.editor, png(), "image")[1]["item"]
        self.assertEqual(self.cms_client.get(f"/manage/{guide.pk}/").status_code, 404)
        for action in ("toggle", "delete", "reads", "preview"):
            response = self.cms_client.post(f"/manage/{guide.pk}/{action}/") if action in ("toggle", "delete") else self.cms_client.get(f"/manage/{guide.pk}/{action}/")
            self.assertEqual(response.status_code, 404, action)
        response, stolen = self.save_post(self.cms_client, title="Кражба", place=self.cms.pk,
                                          body=json.dumps([{"type": "image", "image": {"id": picture["id"]}}]))
        self.assertIsNone(stolen)
        response, foreign = self.save_post(self.cms_client, title="Чуждо място", place=self.marketing.pk)
        self.assertIsNone(foreign)

    def test_superuser_moves_and_pins_and_the_new_department_keeps_the_pin(self):
        picture = self.upload(self.editor, png(), "image")[1]["item"]
        body = json.dumps([{"type": "image", "image": picture}])
        _, guide = self.save_post(self.editor, title="Преместена", body=body)
        boss = self.client_for(self.admin)
        response, _ = self.save_post(boss, url=f"/manage/{guide.pk}/", title="Преместена", place=self.cms.pk,
                                     kind="campaign", is_pinned="on", body=body)
        guide.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(guide.department.pk, self.cms.pk)
        self.assertTrue(guide.is_pinned)
        self.assertEqual(Image.objects.get(pk=picture["id"]).collection_id, department_collection(self.cms).pk)
        self.save_post(self.cms_client, url=f"/manage/{guide.pk}/", title="Преместена", place=self.cms.pk, kind="campaign", body=body)
        guide.refresh_from_db()
        self.assertTrue(guide.is_pinned)  # an editor's save keeps the superuser's „Важно“

    def test_moving_onto_a_taken_address_keeps_both(self):
        boss = self.client_for(self.admin)
        self.save_post(boss, title="Каса", place=self.marketing.pk)
        self.save_post(boss, title="Каса", place=self.cms.pk)
        first = GuidePage.objects.child_of(self.marketing).get()
        second = GuidePage.objects.child_of(self.cms).get()
        response = boss.post(f"/manage/{second.pk}/", self.post_data(title="Каса", place=self.marketing.pk))
        self.assertEqual(response.status_code, 302)
        second.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual((first.url, second.url), ("/marketing/kasa/", "/marketing/kasa-2/"))
        staff = self.client_for(self.pernik_staff)
        self.assertEqual(staff.get(second.url).status_code, 200)
        self.save_post(boss, url=f"/manage/{second.pk}/", title="Каса", place=self.marketing.pk, summary="отново")
        second.refresh_from_db()
        self.assertEqual(second.slug, "kasa-2")  # a later save keeps the new address

    def test_pinned_post_shows_on_the_home_page_until_its_date(self):
        boss = self.client_for(self.admin)
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        _, guide = self.save_post(boss, title="Важна новина", is_pinned="on", pinned_until=tomorrow)
        self.save_post(boss, title="Обикновена новина")
        staff = self.client_for(self.pernik_staff)
        important = '<h2 class="section__title">Важно</h2>'

        def cards(html):
            return html.count('guide-card__title">Важна новина<')

        home = self.html(staff.get("/"))
        self.assertEqual(cards(home), 1)  # once: in „Нови за вас“ while not opened
        self.assertNotIn(important, home)
        staff.get(guide.url)
        home = self.html(staff.get("/"))
        self.assertIn(important, home)
        self.assertEqual(cards(home), 1)  # then in „Важно“, not again under „Последни публикации“
        editor_home = self.html(self.client_for(self.marketing_editor).get("/"))
        self.assertEqual(cards(editor_home), 1)
        GuidePage.objects.filter(pk=guide.pk).update(pinned_until=timezone.localdate() - timedelta(days=1))
        self.assertNotIn(important, self.html(staff.get("/")))


class ArchiveTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        _, self.guide = self.save_post(self.editor, title="Кампания")

    def test_archive_edit_and_back(self):
        response = self.editor.post(f"/manage/{self.guide.pk}/toggle/", {"next": "/manage/?status=active"})
        self.assertEqual(response["Location"], "/manage/?status=active")
        self.guide.refresh_from_db()
        self.assertFalse(self.guide.live)
        self.assertEqual(self.client_for(self.pernik_staff).get(self.guide.url).status_code, 404)
        self.assertContains(self.editor.get("/manage/"), "Върни на сайта")
        self.save_post(self.editor, url=f"/manage/{self.guide.pk}/", title="Кампания (архив)")
        self.guide.refresh_from_db()
        self.assertFalse(self.guide.live)
        self.assertEqual(self.guide.draft_title, "Кампания (архив)")
        self.editor.post(f"/manage/{self.guide.pk}/toggle/")
        self.guide.refresh_from_db()
        self.assertTrue(self.guide.live)
        self.assertEqual(self.guide.title, "Кампания (архив)")

    def test_archive_limit(self):
        with override_settings(INFOHUB_MAX_INACTIVE_PER_DEPARTMENT=0):
            response = self.editor.post(f"/manage/{self.guide.pk}/toggle/", follow=True)
        self.assertContains(response, "архивирани публикации (максимумът)")
        self.guide.refresh_from_db()
        self.assertTrue(self.guide.live)

    def test_moving_an_archived_post_into_a_full_department(self):
        self.editor.post(f"/manage/{self.guide.pk}/toggle/")
        with override_settings(INFOHUB_MAX_INACTIVE_PER_DEPARTMENT=0):
            response, _ = self.save_post(self.client_for(self.admin), url=f"/manage/{self.guide.pk}/", title="Кампания", place=self.cms.pk)
        self.assertContains(response, "архивирани публикации (максимумът)")

    def test_open_redirect_is_ignored(self):
        response = self.editor.post(f"/manage/{self.guide.pk}/toggle/", {"next": "https://evil.example/"})
        self.assertEqual(response["Location"], "/manage/")


class FilesTests(InfoHubTestCase):
    """/media/: login, the right posts only, ranges, safe headers."""

    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)
        self.picture = self.upload(self.editor, png(), "image")[1]["item"]
        self.video = self.upload(self.editor, SimpleUploadedFile("v.mp4", VIDEO), "video")[1]["item"]
        self.pdf = self.upload(self.editor, SimpleUploadedFile("p.pdf", b"%PDF-1.4"), "file")[1]["item"]
        self.xlsx = self.upload(self.editor, SimpleUploadedFile("t.xlsx", b"PK"), "file")[1]["item"]
        body = [{"type": "image", "image": self.picture}, {"type": "video", "document": self.video},
                {"type": "file", "document": self.pdf}, {"type": "file", "document": self.xlsx}]
        self.save_post(self.editor, title="С файлове", body=json.dumps(body))
        self.video_url = Document.objects.get(pk=self.video["id"]).url

    def test_pictures_need_a_login(self):
        from django.test import Client

        response = Client().get(self.picture["thumb"])
        self.assertEqual(response.status_code, 302)
        response = self.staff.get(self.picture["thumb"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(b"".join(response.streaming_content)[:4], b"\x89PNG")

    def test_video_ranges(self):
        response = self.staff.get(self.video_url, HTTP_RANGE="bytes=100-199")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], f"bytes 100-199/{len(VIDEO)}")
        self.assertEqual(b"".join(response.streaming_content), VIDEO[100:200])
        response = self.staff.get(self.video_url, HTTP_RANGE="bytes=-10")
        self.assertEqual(b"".join(response.streaming_content), VIDEO[-10:])
        response = self.staff.get(self.video_url, HTTP_RANGE="bytes=100-")
        self.assertEqual(int(response["Content-Length"]), len(VIDEO) - 100)
        self.assertEqual(self.staff.get(self.video_url, HTTP_RANGE="bytes=999999-").status_code, 416)
        response = self.staff.get(self.video_url, HTTP_RANGE="bytes=abc")
        self.assertEqual(response.status_code, 200)  # unreadable range = whole file
        response = self.staff.get(self.video_url)
        self.assertEqual((response["Accept-Ranges"], int(response["Content-Length"])), ("bytes", len(VIDEO)))

    def test_not_modified(self):
        response = self.staff.get(self.video_url)
        again = self.staff.get(self.video_url, HTTP_IF_MODIFIED_SINCE=response["Last-Modified"])
        self.assertEqual(again.status_code, 304)

    def test_headers_inline_or_download(self):
        response = self.staff.get(Document.objects.get(pk=self.pdf["id"]).url)
        self.assertNotIn("Content-Disposition", response)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertTrue(response["Cache-Control"].startswith("private"))
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")  # shown inside the post
        response = self.staff.get(Document.objects.get(pk=self.xlsx["id"]).url)
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        self.assertEqual(response["X-Frame-Options"], "DENY")

    def test_a_pdf_gets_a_place_in_the_page(self):
        page = self.staff.get(GuidePage.objects.get(title="С файлове").url).content.decode()
        pdf_url = Document.objects.get(pk=self.pdf["id"]).url
        self.assertIn(f'data-pdf-view="{pdf_url}"', page)
        self.assertEqual(page.count("data-pdf-view="), 1)  # not for the Excel file

    def test_no_way_out_of_the_media_folder(self):
        for url in ("/media/../manage.py", "/media/%2e%2e/db.sqlite3", "/media/images/none.png", "/media/..%2fmanage.py"):
            self.assertEqual(self.staff.get(url).status_code, 404, url)

    @override_settings(INFOHUB_MEDIA_ACCEL_REDIRECT="/protected-media/")
    def test_behind_nginx_the_file_is_handed_over(self):
        response = self.staff.get(self.video_url)
        self.assertTrue(response["X-Accel-Redirect"].startswith("/protected-media/documents/"))
        self.assertEqual(response.content, b"")

    def test_logo_is_public(self):
        from django.test import Client
        from home.models import SiteBranding

        logo = Image.objects.create(title="logo", file=png(name="logo.png"))
        guide = GuidePage.objects.get(title="С файлове")
        branding = SiteBranding.for_site(guide.get_site())
        branding.logo = logo
        branding.save()
        url = logo.get_rendition("height-112").url
        self.assertEqual(Client().get(url).status_code, 200)
        self.assertContains(Client().get("/login/"), url)


class CountingTests(InfoHubTestCase):
    def test_views_votes_and_searches_count_only_real_venues(self):
        editor = self.client_for(self.marketing_editor)
        _, guide = self.save_post(editor, title="Принтер")
        staff = self.client_for(self.pernik_staff)
        staff.get(guide.url)
        editor.get(guide.url)
        self.client_for(self.training_staff).get(guide.url)
        staff.get(guide.url, HTTP_SEC_PURPOSE="prefetch")
        self.assertEqual(GuideStat.objects.get(guide=guide).views, 1)
        staff.post(f"/feedback/{guide.pk}/", {"helpful": "yes"})
        staff.post(f"/feedback/{guide.pk}/", {"helpful": "no"})  # second answer ignored
        stat = GuideStat.objects.get(guide=guide)
        self.assertEqual((stat.helpful, stat.not_helpful), (1, 0))
        self.assertContains(staff.get(guide.url), "Отговорихте „Да“")
        self.assertEqual(staff.post(f"/feedback/{guide.pk}/", {"helpful": "maybe"}).status_code, 400)
        self.assertEqual(staff.get(f"/feedback/{guide.pk}/").status_code, 405)
