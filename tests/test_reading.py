"""Drafts and preview, „Нови за вас“, „Прочетох и запознах екипа“ and the „Прочитания“ report."""

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
        response = self.editor.post(f"/manage/{draft.pk}/", self.post_data(title="Готова", action="publish"), follow=True)
        self.assertContains(response, "Публикувано: <a")  # the first time on the site, not „Запазено“
        response = self.editor.post(f"/manage/{draft.pk}/", self.post_data(title="Готова", action="publish"), follow=True)
        self.assertContains(response, "Запазено: <a")  # a change of a live post
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
    """„Прочетох и запознах екипа“: only a venue's manager confirms (the staff account is shared by the
    venue); one manager's confirmation counts for the venue."""

    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)
        self.manager = self.client_for(self.pernik_manager)
        _, self.rules = self.save_post(self.editor, title="Нови правила", all_venues=None, staff_venues=[self.pernik.pk], needs_ack="on")
        # older than the 30 days of „Ново“: only the confirmation keeps it in „Нови за вас“
        GuidePage.objects.filter(pk=self.rules.pk).update(first_published_at=timezone.now() - timedelta(days=90))

    def test_the_manager_confirms(self):
        self.assertTrue(self.rules.needs_ack)
        self.assertIn('name="needs_ack" checked', self.html(self.editor.get(f"/manage/{self.rules.pk}/")))
        unread = section(self.html(self.manager.get("/")), "Нови за вас")
        self.assertIn("Нови правила", unread)
        self.assertIn("badge--ack", unread)
        self.assertIn("когато потвърдите с бутона най-долу", unread)
        page = self.html(self.manager.get(self.rules.url))
        self.assertIn("Прочетете публикацията, запознайте екипа и потвърдете", page)
        self.assertIn(f'action="/read/{self.rules.pk}/"', page)
        self.assertIn(">Прочетох и запознах екипа</button>", page)
        self.assertIn("Нови правила", section(self.html(self.manager.get("/")), "Нови за вас"))  # opening isn't enough
        response = self.manager.post(f"/read/{self.rules.pk}/")
        self.assertTrue(response["Location"].endswith("#ack"))
        page = self.html(self.manager.get(self.rules.url))
        self.assertIn("✓ Потвърдено „Прочетох и запознах екипа“", page)
        self.assertNotIn("(pernik_manager)", section(page, 'id="ack"', "</section>"))  # it was me
        self.assertNotIn("/read/", page)
        self.assertNotIn("Нови правила", section(self.html(self.manager.get("/")), "Нови за вас"))
        self.manager.post(f"/read/{self.rules.pk}/")
        self.assertEqual(Ack.objects.filter(guide=self.rules).count(), 1)

    def test_a_managers_only_post_asks_only_for_read(self):
        """The staff never see it, so the manager isn't asked to brief the team."""
        _, post = self.save_post(self.editor, title="За управители", all_venues=None, manager_venues=[self.pernik.pk], needs_ack="on")
        page = self.html(self.manager.get(post.url))
        self.assertIn("Прочетете публикацията и потвърдете с бутона <b>„Прочетох“</b>", page)
        self.assertIn(">Прочетох</button>", page)
        self.assertNotIn("екипа", page)
        self.manager.post(f"/read/{post.pk}/")
        self.assertIn("✓ Потвърдено „Прочетох“", self.html(self.manager.get(post.url)))
        self.assertIn("Потвърдили „Прочетох“: <b>1 / 1</b>", self.html(self.editor.get(f"/manage/{post.pk}/reads/")))
        self.assertIn("с „Прочетох“.", self.html(self.editor.get(post.url)))

    def test_staff_read_it_like_any_other_post(self):
        self.assertNotIn("Нови правила", section(self.html(self.staff.get("/")), "Нови за вас"))  # older than 30 days
        GuidePage.objects.filter(pk=self.rules.pk).update(first_published_at=timezone.now())
        unread = section(self.html(self.staff.get("/")), "Нови за вас")
        self.assertIn("Нови правила", unread)
        self.assertIn('badge--new">Ново<', unread)
        self.assertNotIn("badge--ack", unread)
        self.assertNotIn("Прочетох", unread)
        page = self.html(self.staff.get(self.rules.url))
        self.assertNotIn("Прочетох", page)
        self.assertNotIn("/read/", page)
        self.assertNotIn("Нови правила", section(self.html(self.staff.get("/")), "Нови за вас"))  # opened: gone
        self.assertIn("Помогна ли ви тази публикация?", page)  # the vote stays for staff
        self.assertIn("Помогна ли ви тази публикация?", self.html(self.manager.get(self.rules.url)))
        # a staff click (old page, typed address) changes nothing
        self.assertTrue(self.staff.post(f"/read/{self.rules.pk}/")["Location"].endswith("#ack"))
        self.assertFalse(Ack.objects.exists())

    def test_one_manager_confirms_for_the_venue(self):
        from venues.access import create_account
        from venues.models import MANAGER

        from .base import PASSWORD

        second = self.client_for(create_account("pernik_manager2", self.pernik, MANAGER, PASSWORD))
        self.assertIn("badge--ack", section(self.html(second.get("/")), "Нови за вас"))
        self.manager.post(f"/read/{self.rules.pk}/")
        self.assertNotIn("Нови правила", section(self.html(second.get("/")), "Нови за вас"))
        page = self.html(second.get(self.rules.url))
        self.assertIn("✓ Потвърдено „Прочетох и запознах екипа“", page)
        self.assertIn("(pernik_manager)", section(page, 'id="ack"', "</section>"))  # who did
        self.assertNotIn("/read/", page)
        reads = self.html(self.editor.get(f"/manage/{self.rules.pk}/reads/"))
        self.assertIn("Потвърдили „Прочетох и запознах екипа“: <b>1 / 1</b> обекта", reads)
        self.assertContains(self.editor.get("/manage/"), "Потвърдили: 1 / 1")

    def test_refused(self):
        _, plain = self.save_post(self.editor, title="Без потвърждение")
        self.assertEqual(self.client_for(self.mladost_manager).post(f"/read/{self.rules.pk}/").status_code, 404)
        self.assertEqual(self.manager.post(f"/read/{plain.pk}/").status_code, 404)
        self.assertRedirects(self.manager.get(f"/read/{self.rules.pk}/"), "/login/", fetch_redirect_response=False)  # button-only: no empty 405
        self.assertEqual(self.manager.post("/read/99999/").status_code, 404)
        self.editor.post(f"/read/{self.rules.pk}/")
        self.assertFalse(Ack.objects.filter(user=self.marketing_editor).exists())
        page = self.html(self.editor.get(self.rules.url))
        self.assertIn("Управителите на обектите потвърждават", page)
        self.assertIn(f"/manage/{self.rules.pk}/reads/", page)
        self.assertNotIn("<button", section(page, 'id="ack"', "</section>"))

    def test_report(self):
        self.staff.get(self.rules.url)
        page = self.html(self.editor.get(f"/manage/{self.rules.pk}/reads/"))
        self.assertIn("pernik_staff", page)
        self.assertIn("pernik_manager", page)
        self.assertNotIn("mladost_", page)
        self.assertIn("Отворили: <b>1 / 2</b>", page)
        self.assertIn("Потвърдили „Прочетох и запознах екипа“: <b>0 / 1</b> обекта", page)
        self.assertIn("Още не са потвърдили: Перник.", page)
        self.assertIn("потвърждава управителят", page)  # the staff row
        self.assertContains(self.editor.get("/manage/"), "Потвърдили: 0 / 1")
        self.manager.post(f"/read/{self.rules.pk}/")
        page = self.html(self.editor.get(f"/manage/{self.rules.pk}/reads/"))
        self.assertIn("Всички обекти потвърдиха.", page)
        self.assertIn("<b>1 / 1</b> обекта", page)
        self.assertContains(self.editor.get("/manage/"), "Потвърдили: 1 / 1")

    def test_staff_confirmations_from_before_dont_count(self):
        Ack.objects.create(guide=self.rules, user=self.pernik_staff)  # kept from before the change
        page = self.html(self.editor.get(f"/manage/{self.rules.pk}/reads/"))
        self.assertIn("<b>0 / 1</b> обекта", page)
        self.assertIn("Още не са потвърдили: Перник.", page)
        self.assertContains(self.editor.get("/manage/"), "Потвърдили: 0 / 1")
        self.assertIn("badge--ack", section(self.html(self.manager.get("/")), "Нови за вас"))

    def test_report_for_all_venues_counts_working_venues_only(self):
        from venues.models import Venue

        Venue.objects.filter(pk=self.sah.pk).update(is_active=False)
        _, everyone = self.save_post(self.editor, title="За всички", needs_ack="on")
        page = self.html(self.editor.get(f"/manage/{everyone.pk}/reads/"))
        self.assertIn("<b>0 / 1</b> обекта", page)
        self.assertNotIn("mladost_", page)
        self.assertNotIn(">staff<", page)  # training

    def test_a_venue_without_a_manager_is_named(self):
        from venues.models import Venue

        Venue.objects.filter(pk=self.sah.pk).update(is_active=True)
        self.mladost_manager.delete()
        _, everyone = self.save_post(self.editor, title="За всички", needs_ack="on")
        page = self.html(self.editor.get(f"/manage/{everyone.pk}/reads/"))
        self.assertIn("<b>0 / 1</b> обекта", page)  # София – Младост can't confirm: not expected
        self.assertIn("Без акаунт на управител (не могат да потвърдят): София – Младост.", page)
        self.assertIn("Още не са потвърдили: Перник.", page)

    def test_only_managers_post(self):
        _, managers = self.save_post(self.editor, title="За управители", all_venues=None,
                                     manager_venues=[self.pernik.pk, self.sah.pk], needs_ack="on")
        page = self.html(self.editor.get(f"/manage/{managers.pk}/reads/"))
        self.assertIn("Отворили: <b>0 / 2</b>", page)
        self.assertIn("<b>0 / 2</b> обекта", page)
        self.assertNotIn("Без акаунт на управител", page)

    def test_moving_a_manager_to_another_venue_forgets_what_it_did(self):
        """A confirmation was given for the old venue: it must not move with the account."""
        boss = self.client_for(self.admin)
        url = f"/manage/users/{self.pernik_manager.pk}/"
        self.manager.get(self.rules.url)
        self.manager.post(f"/read/{self.rules.pk}/")
        boss.post(url, {"username": "pernik_manager", "role": "manager", "venue": self.pernik.pk})  # nothing changed
        self.assertEqual(Ack.objects.filter(user=self.pernik_manager).count(), 1)
        response = boss.post(url, {"username": "pernik_manager", "role": "manager", "venue": self.sah.pk}, follow=True)
        self.assertContains(response, "Потвържденията му „Прочетох“ (при друг обект – и отворените публикации) започват отначало.")
        self.assertFalse(Ack.objects.filter(user=self.pernik_manager).exists())
        self.assertFalse(Seen.objects.filter(user=self.pernik_manager).exists())
        _, everyone = self.save_post(self.editor, title="За всички", needs_ack="on")
        page = self.html(self.editor.get(f"/manage/{everyone.pk}/reads/"))
        self.assertIn("<b>0 / 1</b> обекта", page)  # Перник has no manager now; Младост has two
        self.assertIn("Без акаунт на управител (не могат да потвърдят): Перник.", page)

    def test_a_role_change_forgets_the_confirmations(self):
        boss = self.client_for(self.admin)
        Ack.objects.create(guide=self.rules, user=self.pernik_staff)  # a staff click from before the change
        self.staff.get(self.rules.url)
        boss.post(f"/manage/users/{self.pernik_staff.pk}/", {"username": "pernik_staff", "role": "manager", "venue": self.pernik.pk})
        self.assertFalse(Ack.objects.filter(user=self.pernik_staff).exists())  # would count as the venue's now
        self.assertTrue(Seen.objects.filter(user=self.pernik_staff).exists())  # same venue: still opened
        self.assertContains(self.editor.get(f"/manage/{self.rules.pk}/reads/"), "<b>0 / 1</b> обекта")

    def test_confirmations_of_venues_no_longer_in_the_audience_dont_count(self):
        self.manager.post(f"/read/{self.rules.pk}/")
        self.assertContains(self.editor.get("/manage/"), "Потвърдили: 1 / 1")
        self.save_post(self.editor, url=f"/manage/{self.rules.pk}/", title="Нови правила", all_venues=None,
                       manager_venues=[self.sah.pk], needs_ack="on")
        self.assertContains(self.editor.get("/manage/"), "Потвърдили: 0 / 1")
        page = self.html(self.editor.get(f"/manage/{self.rules.pk}/reads/"))
        self.assertIn("Още не са потвърдили: София – Младост.", page)
        self.assertNotIn("pernik_", page)

    def test_the_training_manager_can_try_it_but_isnt_counted(self):
        from venues.models import MANAGER

        trainer = self.training.accounts.get(role=MANAGER).user
        from .base import PASSWORD

        trainer.set_password(PASSWORD)
        trainer.save()
        client = self.client_for(trainer)
        _, everyone = self.save_post(self.editor, title="За всички", needs_ack="on")
        self.assertIn(">Прочетох и запознах екипа</button>", self.html(client.get(everyone.url)))
        client.post(f"/read/{everyone.pk}/")
        self.assertIn("✓ Потвърдено", self.html(client.get(everyone.url)))
        self.assertContains(self.editor.get(f"/manage/{everyone.pk}/reads/"), "<b>0 / 2</b> обекта")

    def test_widened_to_the_staff_a_plain_read_no_longer_counts(self):
        """„Прочетох“ on a managers-only post doesn't promise a briefing: once the post reaches the
        staff, the manager is asked again; the other way round a confirmation keeps counting."""
        _, post = self.save_post(self.editor, title="Промяна", all_venues=None, manager_venues=[self.pernik.pk], needs_ack="on")
        self.manager.post(f"/read/{post.pk}/")
        self.assertFalse(Ack.objects.get(guide=post).team)
        self.assertContains(self.editor.get(f"/manage/{post.pk}/reads/"), "<b>1 / 1</b> обекта")
        self.save_post(self.editor, url=f"/manage/{post.pk}/", title="Промяна", all_venues=None,
                       staff_venues=[self.pernik.pk], needs_ack="on")
        page = self.html(self.manager.get(post.url))
        self.assertIn(">Прочетох и запознах екипа</button>", page)
        self.assertNotIn("✓ Потвърдено", page)
        self.assertIn("Промяна", section(self.html(self.manager.get("/")), "Нови за вас"))
        reads = self.html(self.editor.get(f"/manage/{post.pk}/reads/"))
        self.assertIn("<b>0 / 1</b> обекта", reads)
        self.assertIn("Още не са потвърдили: Перник", reads)
        self.assertIn("Потвърдили: 0 / 1", self.html(self.editor.get("/manage/")))
        self.manager.post(f"/read/{post.pk}/")
        self.assertTrue(Ack.objects.get(guide=post).team)
        self.assertIn("✓ Потвърдено „Прочетох и запознах екипа“", self.html(self.manager.get(post.url)))
        self.assertContains(self.editor.get(f"/manage/{post.pk}/reads/"), "<b>1 / 1</b> обекта")
        # narrowed back to managers only: the briefing promise still covers „Прочетох“
        self.save_post(self.editor, url=f"/manage/{post.pk}/", title="Промяна", all_venues=None,
                       manager_venues=[self.pernik.pk], needs_ack="on")
        self.assertIn("✓ Потвърдено „Прочетох“", self.html(self.manager.get(post.url)))
        self.assertContains(self.editor.get(f"/manage/{post.pk}/reads/"), "<b>1 / 1</b> обекта")

    def test_switching_the_request_off(self):
        self.save_post(self.editor, url=f"/manage/{self.rules.pk}/", title="Нови правила", all_venues=None,
                       staff_venues=[self.pernik.pk])
        GuidePage.objects.filter(pk=self.rules.pk).update(first_published_at=timezone.now() - timedelta(days=90))
        self.assertNotIn("Нови правила", section(self.html(self.manager.get("/")), "Нови за вас"))
        self.assertNotIn("/read/", self.html(self.manager.get(self.rules.url)))
        self.assertEqual(self.manager.post(f"/read/{self.rules.pk}/").status_code, 404)
        self.assertNotContains(self.editor.get("/manage/"), "Потвърдили:")

    def test_report_access(self):
        self.assertTrue(self.staff.get(f"/manage/{self.rules.pk}/reads/")["Location"].startswith("/login/"))
        self.assertEqual(self.client_for(self.cms_editor).get(f"/manage/{self.rules.pk}/reads/").status_code, 404)
        _, plain = self.save_post(self.editor, title="Без потвърждение")
        page = self.html(self.editor.get(f"/manage/{plain.pk}/reads/"))
        self.assertIn("Отворили", page)
        self.assertNotIn("Потвърдили", page)
        self.assertNotIn("Всички обекти потвърдиха", page)
