"""„Важна промяна“ (guides/changes.py) and the categories on the home page's section cards."""

from datetime import timedelta

from django.utils import timezone

from guides.models import CategoryPage, GuideChange, GuidePage
from guides.publishing import save_guide
from stats.models import Ack, Seen
from stats.reading import ack_progress

from .base import InfoHubTestCase
from .test_reading import section


def unread(html):
    return section(html, "Нови за вас")


class ImportantChangeTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)
        self.manager = self.client_for(self.pernik_manager)
        _, self.post = self.save_post(self.editor, title="Работно време")
        self.url = f"/manage/{self.post.pk}/"
        self.staff.get(self.post.url)  # opened: no longer in „Нови за вас“
        self.assertNotIn("Работно време", unread(self.html(self.staff.get("/"))))

    def edit(self, **changes):
        base = GuidePage.objects.get(pk=self.post.pk).latest_revision_id
        return self.save_post(self.editor, url=self.url, title="Работно време", base_revision=base, **changes)

    def test_offered_only_for_a_post_published_before(self):
        self.assertIn('name="important"', self.html(self.editor.get(self.url)))
        self.assertNotIn('name="important"', self.html(self.editor.get("/manage/new/")))
        _, draft = self.save_post(self.editor, title="Чернова", action="draft")
        self.assertNotIn('name="important"', self.html(self.editor.get(f"/manage/{draft.pk}/")))
        # a first publish is new anyway: a crafted tick is ignored
        self.save_post(self.editor, url=f"/manage/{draft.pk}/", title="Чернова", important="on", change_note="x")
        self.assertFalse(GuideChange.objects.filter(guide_id=draft.pk).exists())

    def test_a_small_fix_doesnt_bring_it_back(self):
        response, _ = self.edit(summary="поправка")
        self.assertNotIn("Показва се отново", self.html(self.editor.get(response["Location"])))
        self.assertFalse(GuideChange.objects.exists())
        self.assertNotIn("Работно време", unread(self.html(self.staff.get("/"))))

    def test_an_important_change_brings_it_back_until_opened_again(self):
        response, _ = self.edit(important="on", change_note="Ново работно време от 1 декември")
        self.assertIn("Показва се отново на обектите като „Обновено“", self.html(self.editor.get(response["Location"])))
        home = self.html(self.staff.get("/"))
        self.assertIn("Работно време", unread(home))
        self.assertIn('badge--new">Обновено<', unread(home))
        self.assertIn("Променено: Ново работно време от 1 декември", unread(home))
        page = self.html(self.staff.get(self.post.url))
        self.assertIn("Важна промяна", page)
        self.assertIn("Ново работно време от 1 декември", page)
        self.assertNotIn("Работно време", unread(self.html(self.staff.get("/"))))
        self.assertEqual(Seen.objects.filter(user=self.pernik_staff).count(), 1)  # moved on, not doubled
        # also those who never opened it, even a post older than the 30 days of „Ново“
        GuidePage.objects.filter(pk=self.post.pk).update(first_published_at=timezone.now() - timedelta(days=90))
        self.assertIn("Работно време", unread(self.html(self.manager.get("/"))))

    def test_without_a_note(self):
        self.edit(important="on")
        self.assertNotIn("Променено:", self.html(self.staff.get("/")))
        self.assertIn("публикацията е обновена", self.html(self.staff.get(self.post.url)))

    def test_the_note_is_shown_as_text(self):
        self.edit(important="on", change_note="<script>alert(1)</script>")
        page = self.html(self.staff.get(self.post.url))
        self.assertNotIn("<script>alert(1)", page)
        self.assertIn("&lt;script&gt;alert(1)", page)

    def test_a_note_without_the_tick_is_refused(self):
        response, _ = self.edit(change_note="забравена отметка", summary="нещо ново")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Отметнете „Важна промяна“ или изтрийте текста", self.html(response))
        self.assertEqual(GuidePage.objects.get(pk=self.post.pk).summary, "")

    def test_an_old_change_no_longer_counts(self):
        self.edit(important="on", change_note="старо")
        GuideChange.objects.update(at=timezone.now() - timedelta(days=31))
        self.assertNotIn("Работно време", unread(self.html(self.staff.get("/"))))
        self.assertNotIn("Важна промяна", self.html(self.staff.get(self.post.url)))

    def test_editors_see_no_section(self):
        self.edit(important="on")
        self.assertNotIn("Нови за вас", self.html(self.editor.get("/")))

    def test_saved_as_draft_it_waits_for_publishing(self):
        response, _ = self.edit(important="on", change_note="Нов формуляр", action="draft")
        self.assertIn("Важната промяна ще им се покаже при публикуване", self.html(self.editor.get(response["Location"])))
        self.assertTrue(GuideChange.objects.get().pending)
        self.assertNotIn("Работно време", unread(self.html(self.staff.get("/"))))
        page = self.html(self.editor.get(self.url))
        self.assertIn('name="important" data-important checked', page)
        self.assertIn('value="Нов формуляр"', page)
        self.assertIn("ще се покаже на обектите при публикуване", page)
        self.edit(important="on", change_note="Нов формуляр")
        change = GuideChange.objects.get()
        self.assertFalse(change.pending)
        self.assertIn("Работно време", unread(self.html(self.staff.get("/"))))

    def test_unticked_on_the_next_save_it_is_dropped(self):
        self.edit(important="on", action="draft")
        self.edit()
        self.assertFalse(GuideChange.objects.exists())
        self.assertNotIn("Работно време", unread(self.html(self.staff.get("/"))))

    def test_an_archived_post_shows_it_when_back_on_the_site(self):
        self.editor.post(f"/manage/{self.post.pk}/toggle/")
        response, _ = self.edit(important="on", change_note="Нови цени")
        self.assertIn("ще се покаже на обектите, когато я върнете на сайта", self.html(self.editor.get(response["Location"])))
        self.assertTrue(GuideChange.objects.get().pending)
        self.editor.post(f"/manage/{self.post.pk}/toggle/")
        self.assertFalse(GuideChange.objects.get().pending)
        self.assertIn("Нови цени", unread(self.html(self.staff.get("/"))))

    def test_history_and_reads_show_it(self):
        self.edit(important="on", change_note="Нов телефон")
        history = self.html(self.editor.get(f"/manage/{self.post.pk}/history/"))
        self.assertIn("Важна промяна", history)
        self.assertIn("Нов телефон", history)
        reads = self.html(self.editor.get(f"/manage/{self.post.pk}/reads/"))
        self.assertIn("Отворили след важната промяна", reads)
        self.assertIn("не след промяната (по-рано:", reads)  # Перник's staff opened the old version
        self.staff.get(self.post.url)
        self.assertNotIn("не след промяната", self.html(self.editor.get(f"/manage/{self.post.pk}/reads/")))


class ReconfirmTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.manager = self.client_for(self.pernik_manager)
        _, self.post = self.save_post(self.editor, title="Правила", all_venues=None, staff_venues=[self.pernik.pk], needs_ack="on")
        self.url = f"/manage/{self.post.pk}/"
        self.manager.post(f"/read/{self.post.pk}/")
        self.assertEqual(ack_progress(self.post), (1, 1))

    def edit(self, **changes):
        base = GuidePage.objects.get(pk=self.post.pk).latest_revision_id
        return self.save_post(self.editor, url=self.url, title="Правила", all_venues=None, staff_venues=[self.pernik.pk],
                              base_revision=base, **changes)

    def test_an_important_change_alone_keeps_the_confirmations(self):
        self.edit(needs_ack="on", important="on")
        self.assertEqual(ack_progress(self.post), (1, 1))
        self.assertIn("✓ Потвърдено", self.html(self.manager.get(self.post.url)))

    def test_a_new_confirmation_is_asked(self):
        self.edit(needs_ack="on", important="on", reconfirm="on", change_note="Нова точка 4")
        self.assertEqual(ack_progress(self.post), (0, 1))
        home = self.html(self.manager.get("/"))
        self.assertIn("badge--ack", unread(home))
        page = self.html(self.manager.get(self.post.url))
        self.assertIn(f'action="/read/{self.post.pk}/"', page)
        reads = self.html(self.editor.get(f"/manage/{self.post.pk}/reads/"))
        self.assertIn("Потвърдили „Прочетох и запознах екипа“ новата версия", reads)
        self.assertIn("(по-рано:", reads)
        self.manager.post(f"/read/{self.post.pk}/")
        self.assertEqual(ack_progress(self.post), (1, 1))
        self.assertEqual(Ack.objects.count(), 1)  # the same row, given again
        self.assertNotIn("Правила", unread(self.html(self.manager.get("/"))))

    def test_the_reconfirm_tick_alone_means_an_important_change(self):
        self.edit(needs_ack="on", reconfirm="on")
        self.assertTrue(GuideChange.objects.get().reconfirm)

    def test_no_new_confirmation_on_a_post_that_doesnt_ask(self):
        self.edit(important="on", reconfirm="on")
        self.assertFalse(GuideChange.objects.get().reconfirm)

    def test_a_pending_new_confirmation_doesnt_count_yet(self):
        self.edit(needs_ack="on", important="on", reconfirm="on", action="draft")
        self.assertEqual(ack_progress(self.post), (1, 1))


class SaveGuideTests(InfoHubTestCase):
    def test_change_on_a_first_publish_is_ignored(self):
        page = save_guide(user=self.admin, parent=self.marketing, title="Нова", summary="", kind="news",
                          is_pinned=False, pinned_until=None, body="[]", change=("бележка", False))
        self.assertTrue(page.live)
        self.assertFalse(GuideChange.objects.exists())


def card(html, title):
    """The home page's section card of `title`."""
    for part in html.split('<div class="dept-card ')[1:]:
        if f"<span>{title}</span>" in part:
            return part.split("</div>", 1)[0]
    return ""


class CategoryCardTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)

    def category(self, title):
        self.editor.post("/manage/categories/", {"department": self.marketing.pk, "title": title})
        return CategoryPage.objects.get(title=title)

    def test_without_categories_the_card_lists_posts(self):
        self.save_post(self.editor, title="Есенна томбола")
        marketing = card(self.html(self.staff.get("/")), "Маркетинг")
        self.assertIn("Есенна томбола", marketing)
        self.assertNotIn("dept-card__categories", marketing)

    def test_categories_instead_of_posts(self):
        promos, raffles = self.category("Промоции"), self.category("Томболи")
        self.category("Празна")
        self.save_post(self.editor, title="Рожден ден", place=promos.pk)
        self.save_post(self.editor, title="Есенна томбола", place=raffles.pk)
        self.save_post(self.editor, title="Без категория")
        marketing = card(self.html(self.staff.get("/")), "Маркетинг")
        self.assertIn(f'href="{promos.url}">Промоции</a> <span>1</span>', marketing)
        self.assertIn("Томболи", marketing)
        self.assertNotIn("Празна", marketing)  # nothing in it
        self.assertIn(f'href="{self.marketing.url}?other=1">Други</a> <span>1</span>', marketing)
        self.assertNotIn("Рожден ден", marketing)
        self.assertIn("Всички (3)", marketing)
        others = self.html(self.staff.get(f"{self.marketing.url}?other=1"))
        self.assertIn("Без категория", others)
        self.assertNotIn("Рожден ден", others)
        page = self.html(self.staff.get(self.marketing.url))
        self.assertNotIn("Празна", page)
        self.assertIn("Рожден ден", page)

    def test_a_category_only_for_managers_is_hidden_from_staff(self):
        promos, secret = self.category("Промоции"), self.category("За управители")
        self.save_post(self.editor, title="Рожден ден", place=promos.pk)
        self.save_post(self.editor, title="Бонуси", place=secret.pk, all_venues=None, manager_venues=[self.pernik.pk])
        self.assertNotIn("За управители", card(self.html(self.staff.get("/")), "Маркетинг"))
        self.assertIn("За управители", card(self.html(self.client_for(self.pernik_manager).get("/")), "Маркетинг"))

    def test_at_most_six_then_more(self):
        for number in range(1, 8):
            self.save_post(self.editor, title=f"Пост {number}", place=self.category(f"Категория {number}").pk)
        marketing = card(self.html(self.staff.get("/")), "Маркетинг")
        self.assertIn("Категория 6", marketing)
        self.assertNotIn("Категория 7", marketing)
        self.assertIn("Още 1 →", marketing)

    def test_order(self):
        first, second = self.category("Първа"), self.category("Втора")
        self.save_post(self.editor, title="А", place=first.pk)
        self.save_post(self.editor, title="Б", place=second.pk)
        marketing = card(self.html(self.staff.get("/")), "Маркетинг")
        self.assertLess(marketing.index("Първа"), marketing.index("Втора"))
        self.assertIn('value="up" class="link-button" title="Нагоре" aria-label="Първа нагоре" disabled', self.html(self.editor.get("/manage/categories/")))
        self.editor.post(f"/manage/categories/{second.pk}/move/", {"direction": "up"})
        marketing = card(self.html(self.staff.get("/")), "Маркетинг")
        self.assertLess(marketing.index("Втора"), marketing.index("Първа"))
        self.assertIn("Втора", self.html(self.staff.get(second.url)))  # the address still works
        # another section's editor can't move it
        self.assertEqual(self.client_for(self.cms_editor).post(f"/manage/categories/{first.pk}/move/", {"direction": "up"}).status_code, 404)
        self.assertEqual(self.staff.post(f"/manage/categories/{first.pk}/move/", {"direction": "up"}).status_code, 302)
