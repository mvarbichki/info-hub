"""Drafts and preview, „Нови за вас“, „Прочетох“ and the „Прочитания“ report."""

from datetime import timedelta

from django.utils import timezone

from guides.models import GuidePage
from guides.publishing import inactive_count
from stats.models import Ack, GuideStat, Seen

from .base import InfoHubTestCase


def section(html, start, end='<section class="section">'):
    """The part of a page from `start` to the next section ("" when `start` isn't there)."""
    return html.split(start, 1)[1].split(end, 1)[0] if start in html else ""


class DraftTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)

    def test_a_draft_stays_off_the_site(self):
        response, draft = self.save_post(self.editor, title="Коледна кампания", kind="campaign", action="draft")
        self.assertRedirects(response, f"/manage/{draft.pk}/", fetch_redirect_response=False)
        self.assertTrue(draft.is_draft)
        self.assertEqual(draft.kind, "campaign")  # the list shows the draft's own type
        page = self.html(self.editor.get(f"/manage/{draft.pk}/"))
        self.assertIn("Черновата на „Коледна кампания“ е запазена", page)
        self.assertIn(f"/manage/{draft.pk}/preview/", page)
        self.assertIn('value="draft"', page)
        self.assertEqual(self.staff.get(draft.url).status_code, 404)
        self.assertNotIn("Коледна кампания", self.html(self.staff.get("/")) + self.html(self.staff.get("/search/?q=коледна")))
        self.assertIn("Коледна кампания", self.html(self.editor.get("/manage/?status=draft")))
        self.assertNotIn("Коледна кампания", self.html(self.editor.get("/manage/?status=inactive")))
        self.assertEqual(inactive_count(self.marketing), 0)

    def test_preview_is_for_its_editors_only(self):
        _, draft = self.save_post(self.editor, title="Преглед", action="draft")
        response = self.editor.get(f"/manage/{draft.pk}/preview/")
        self.assertContains(response, "Преглед: така ще изглежда")
        self.assertFalse(GuideStat.objects.exists() or Seen.objects.exists())
        self.assertTrue(self.staff.get(f"/manage/{draft.pk}/preview/")["Location"].startswith("/login/"))
        self.assertEqual(self.client_for(self.cms_editor).get(f"/manage/{draft.pk}/preview/").status_code, 404)

    def test_publishing_a_draft(self):
        _, draft = self.save_post(self.editor, title="Готова", action="draft")
        self.save_post(self.editor, url=f"/manage/{draft.pk}/", title="Готова", action="publish")
        draft.refresh_from_db()
        self.assertTrue(draft.live and draft.first_published_at)
        self.assertEqual(self.staff.get(draft.url).status_code, 200)
        _, other = self.save_post(self.editor, title="От списъка", action="draft")
        response = self.editor.post(f"/manage/{other.pk}/toggle/", follow=True)
        self.assertContains(response, "„От списъка“ е публикувана.")

    def test_draft_of_a_live_post_keeps_the_published_version(self):
        _, post = self.save_post(self.editor, title="Работно време", all_venues=None, staff_venues=[self.pernik.pk])
        self.save_post(self.editor, url=f"/manage/{post.pk}/", title="Работно време (ново)", all_venues=None,
                       staff_venues=[self.sah.pk], action="draft")
        post.refresh_from_db()
        self.assertEqual((post.title, list(post.venues.all())), ("Работно време", [self.pernik]))
        self.assertTrue(post.has_unpublished_changes)
        self.assertContains(self.staff.get(post.url), "Работно време")
        self.assertEqual(self.client_for(self.mladost_staff).get(post.url).status_code, 404)
        page = self.html(self.editor.get(f"/manage/{post.pk}/"))
        self.assertIn('value="Работно време (ново)"', page)
        self.assertIn("Публикувай промените", page)
        self.assertIn("има чернова", self.html(self.editor.get("/manage/")))
        self.assertContains(self.editor.get(f"/manage/{post.pk}/preview/"), "Работно време (ново)")
        self.save_post(self.editor, url=f"/manage/{post.pk}/", title="Работно време (ново)", all_venues=None,
                       staff_venues=[self.sah.pk], action="publish")
        post.refresh_from_db()
        self.assertEqual(post.title, "Работно време (ново)")
        self.assertEqual(self.staff.get(post.url).status_code, 404)

    def test_archived_post_has_no_draft_button_and_stays_archived(self):
        _, post = self.save_post(self.editor, title="Архив")
        self.editor.post(f"/manage/{post.pk}/toggle/")
        page = self.html(self.editor.get(f"/manage/{post.pk}/"))
        self.assertNotIn('value="draft"', page)
        self.save_post(self.editor, url=f"/manage/{post.pk}/", title="Архив 2", action="draft")
        post.refresh_from_db()
        self.assertFalse(post.live or post.is_draft)


class UnreadTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)
        _, self.new = self.save_post(self.editor, title="Нова кампания")
        _, self.old = self.save_post(self.editor, title="Стара новина")
        GuidePage.objects.filter(pk=self.old.pk).update(first_published_at=timezone.now() - timedelta(days=40))

    def test_new_posts_wait_at_the_top_until_opened(self):
        home = self.html(self.staff.get("/"))
        unread = section(home, "Нови за вас")
        self.assertIn("Нови за вас (1)", home)
        self.assertIn("Нова кампания", unread)
        self.assertNotIn("Стара новина", unread)
        self.assertIn('badge--new">Ново<', unread)
        self.assertNotIn("Нова кампания", section(home, "Последни публикации"))  # not shown twice
        self.staff.get(self.new.url)
        home = self.html(self.staff.get("/"))
        self.assertNotIn("Нови за вас", home)
        self.assertNotIn('badge--new">Ново<', home)

    def test_per_account(self):
        self.staff.get(self.new.url)
        self.staff.get(self.new.url)
        self.assertEqual(Seen.objects.filter(user=self.pernik_staff).count(), 1)
        self.assertIn("Нови за вас (1)", self.html(self.client_for(self.pernik_manager).get("/")))

    def test_who_is_remembered(self):
        self.editor.get(self.new.url)
        self.staff.get(self.new.url, HTTP_SEC_PURPOSE="prefetch")
        self.assertFalse(Seen.objects.exists())
        self.client_for(self.training_staff).get(self.new.url)
        self.assertTrue(Seen.objects.filter(user=self.training_staff).exists())

    def test_editors_see_the_seven_day_label_and_no_section(self):
        home = self.html(self.editor.get("/"))
        self.assertIn('badge--new">Ново<', home)
        self.assertNotIn("Нови за вас", home)


class AcknowledgeTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)
        self.manager = self.client_for(self.pernik_manager)
        _, self.rules = self.save_post(self.editor, title="Нови правила", all_venues=None, staff_venues=[self.pernik.pk], needs_ack="on")

    def test_flow(self):
        self.assertTrue(self.rules.needs_ack)
        self.assertIn('name="needs_ack" checked', self.html(self.editor.get(f"/manage/{self.rules.pk}/")))
        GuidePage.objects.filter(pk=self.rules.pk).update(first_published_at=timezone.now() - timedelta(days=90))
        unread = section(self.html(self.staff.get("/")), "Нови за вас")
        self.assertIn("Нови правила", unread)
        self.assertIn("badge--ack", unread)
        page = self.html(self.staff.get(self.rules.url))
        self.assertIn("Прочетете публикацията и потвърдете", page)
        self.assertIn(f'action="/read/{self.rules.pk}/"', page)
        self.assertIn("Нови правила", section(self.html(self.staff.get("/")), "Нови за вас"))  # opening isn't enough
        response = self.staff.post(f"/read/{self.rules.pk}/")
        self.assertTrue(response["Location"].endswith("#ack"))
        page = self.html(self.staff.get(self.rules.url))
        self.assertIn("Потвърдихте, че сте прочели", page)
        self.assertNotIn("/read/", page)
        self.assertNotIn("Нови правила", section(self.html(self.staff.get("/")), "Нови за вас"))
        self.staff.post(f"/read/{self.rules.pk}/")
        self.assertEqual(Ack.objects.filter(guide=self.rules).count(), 1)

    def test_refused(self):
        _, plain = self.save_post(self.editor, title="Без потвърждение")
        self.assertEqual(self.client_for(self.mladost_staff).post(f"/read/{self.rules.pk}/").status_code, 404)
        self.assertEqual(self.staff.post(f"/read/{plain.pk}/").status_code, 404)
        self.assertEqual(self.staff.get(f"/read/{self.rules.pk}/").status_code, 405)
        self.assertEqual(self.staff.post("/read/99999/").status_code, 404)
        self.editor.post(f"/read/{self.rules.pk}/")
        self.assertFalse(Ack.objects.filter(user=self.marketing_editor).exists())
        self.assertContains(self.editor.get(self.rules.url), f"/manage/{self.rules.pk}/reads/")

    def test_report(self):
        self.staff.get(self.rules.url)
        self.staff.post(f"/read/{self.rules.pk}/")
        page = self.html(self.editor.get(f"/manage/{self.rules.pk}/reads/"))
        self.assertIn("pernik_staff", page)
        self.assertIn("pernik_manager", page)
        self.assertNotIn("mladost_", page)
        self.assertIn("Отворили: <b>1 / 2</b>", page)
        self.assertIn("„Прочетох“: <b>1 / 2</b>", page)
        self.assertIn("Още не са потвърдили: Перник (управител).", page)
        self.manager.post(f"/read/{self.rules.pk}/")
        self.assertContains(self.editor.get(f"/manage/{self.rules.pk}/reads/"), "Всички обекти потвърдиха")
        self.assertContains(self.editor.get("/manage/"), "Прочетох: 2 / 2")

    def test_report_for_all_venues_counts_working_venues_only(self):
        from venues.models import Venue

        Venue.objects.filter(pk=self.sah.pk).update(is_active=False)
        _, everyone = self.save_post(self.editor, title="За всички", needs_ack="on")
        page = self.html(self.editor.get(f"/manage/{everyone.pk}/reads/"))
        self.assertIn("„Прочетох“: <b>0 / 2</b>", page)
        self.assertNotIn("mladost_", page)
        self.assertNotIn(">staff<", page)  # training

    def test_report_access(self):
        self.assertTrue(self.staff.get(f"/manage/{self.rules.pk}/reads/")["Location"].startswith("/login/"))
        self.assertEqual(self.client_for(self.cms_editor).get(f"/manage/{self.rules.pk}/reads/").status_code, 404)
        _, plain = self.save_post(self.editor, title="Без потвърждение")
        page = self.html(self.editor.get(f"/manage/{plain.pk}/reads/"))
        self.assertIn("Отворили", page)
        self.assertNotIn("„Прочетох“:", page)
