"""Who sees which post: the three audience modes, labels, lists, search, files, chips, venue changes."""

import json
import re

from django.test import Client
from wagtail.images.models import Image

from guides.audience import AudienceError, normalize, posts_only_for, summary
from guides.models import GuidePage
from stats.models import GuideStat, SearchStat

from .base import PASSWORD, InfoHubTestCase, png


class NormalizeTests(InfoHubTestCase):
    def test_choices_are_stored_tidy(self):
        self.assertEqual(normalize(True, [self.pernik], [self.sah]), ("all", []))
        self.assertEqual(normalize(False, [self.pernik], []), ("staff", [self.pernik]))
        self.assertEqual(normalize(False, [], [self.sah]), ("managers", [self.sah]))
        with self.assertRaisesMessage(AudienceError, "не двете заедно"):
            normalize(False, [self.pernik], [self.sah])
        with self.assertRaisesMessage(AudienceError, "Изберете кой да вижда"):
            normalize(False, [], [])


class VisibilityTests(InfoHubTestCase):
    """Six posts, five venue accounts: each opens and lists exactly its own."""

    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.pic_all = self.upload(self.editor, png(color="white"), "image")[1]["item"]
        self.pic_mgr = self.upload(self.editor, png(color="purple"), "image")[1]["item"]
        self.A = self.post("За всички", {"all_venues": "on"}, [self.pic_all])
        self.B = self.post("Перник служители", {"staff_venues": [self.pernik.pk]})
        self.C = self.post("Перник управител управителскатайна", {"manager_venues": [self.pernik.pk]}, [self.pic_mgr])
        self.D = self.post("Двама управители", {"manager_venues": [self.pernik.pk, self.sah.pk]})
        self.E = self.post("Два обекта", {"staff_venues": [self.sah.pk, self.pernik.pk]})
        self.H = self.post("Всички плюс списък", {"all_venues": "on", "staff_venues": [self.sah.pk]})
        self.everyone = [self.A, self.B, self.C, self.D, self.E, self.H]
        self.clients = {
            "pernik_staff": self.client_for(self.pernik_staff),
            "pernik_manager": self.client_for(self.pernik_manager),
            "mladost_staff": self.client_for(self.mladost_staff),
            "mladost_manager": self.client_for(self.mladost_manager),
            "training": self.client_for(self.training_staff),
        }

    def post(self, title, audience, images=()):
        body = [{"type": "text", "html": f"<p>{title} тайнаxyz</p>"}] + [{"type": "image", "image": i} for i in images]
        data = {"title": title, "summary": "", "place": self.marketing.pk, "kind": "news", "body": json.dumps(body), **audience}
        self.assertEqual(self.editor.post("/manage/new/", data).status_code, 302, title)
        return GuidePage.objects.get(title=title)

    def test_stored_tidy(self):
        self.assertEqual((self.H.audience, list(self.H.venues.all())), ("all", []))
        self.assertEqual((self.B.audience, list(self.B.venues.all())), ("staff", [self.pernik]))
        self.assertEqual(self.C.audience, "managers")

    def test_each_account_opens_and_lists_exactly_its_posts(self):
        allowed = {
            "pernik_staff": {self.A, self.B, self.E, self.H},
            "pernik_manager": {self.A, self.B, self.C, self.D, self.E, self.H},
            "mladost_staff": {self.A, self.E, self.H},
            "mladost_manager": {self.A, self.D, self.E, self.H},
            "training": {self.A, self.H},
        }
        for who, client in self.clients.items():
            listing = self.html(client.get("/marketing/")) + self.html(client.get("/search/?q=тайнаxyz")) + self.html(client.get("/"))
            for post in self.everyone:
                with self.subTest(who=who, post=post.title):
                    self.assertEqual(client.get(post.url).status_code == 200, post in allowed[who])
                    self.assertEqual(post.title in listing, post in allowed[who])

    def test_editors_see_every_post(self):
        html = self.html(self.editor.get("/search/?q=тайнаxyz"))
        for post in self.everyone:
            self.assertIn(post.title, html)

    def badge(self, who, post):
        match = re.search(r'badge--audience[^"]*">([^<]*)<', self.html(self.clients[who].get(post.url)))
        return match.group(1) if match else ""

    def test_labels(self):
        self.assertEqual(self.badge("pernik_staff", self.B), "За вашия обект")
        self.assertEqual(self.badge("pernik_staff", self.A), "")
        self.assertEqual(self.badge("pernik_manager", self.C), "Само за управители")
        self.assertEqual(self.badge("pernik_manager", self.E), "За вашия обект")
        self.assertEqual(self.badge("mladost_manager", self.D), "Само за управители")
        self.assertIn('badge--audience badge--managers">Само за управители', self.html(self.clients["pernik_manager"].get(self.C.url)))

    def test_nothing_for_managers_ever_reaches_a_staff_page(self):
        for who in ("pernik_staff", "mladost_staff", "training"):
            client = self.clients[who]
            pages = [self.html(client.get(url)) for url in ("/", "/marketing/", "/search/?q=тайнаxyz", "/search/?q=управител")]
            pages += [self.html(r) for r in (client.get(p.url) for p in self.everyone) if r.status_code == 200]
            for html in pages:
                self.assertNotIn("Само за управители", html)
                self.assertNotIn(self.C.title, html)
                self.assertNotIn(self.D.title, html)

    def test_files_follow_their_post(self):
        image = Image.objects.get(pk=self.pic_mgr["id"])
        for url in (image.file.url, image.get_rendition("max-1600x1600").url):
            self.assertEqual(self.clients["pernik_staff"].get(url).status_code, 404)
            self.assertEqual(self.clients["mladost_manager"].get(url).status_code, 404)
            self.assertEqual(self.clients["pernik_manager"].get(url).status_code, 200)
            self.assertEqual(self.editor.get(url).status_code, 200)
        self.assertEqual(self.clients["pernik_staff"].get(Image.objects.get(pk=self.pic_all["id"]).file.url).status_code, 200)
        loose = Image.objects.get(pk=self.upload(self.editor, png(color="orange"), "image")[1]["item"]["id"])
        self.assertEqual(self.clients["pernik_manager"].get(loose.file.url).status_code, 404)
        self.assertEqual(self.editor.get(loose.file.url).status_code, 200)

    def test_feedback_only_on_own_posts(self):
        self.assertEqual(self.clients["pernik_staff"].post(f"/feedback/{self.C.pk}/", {"helpful": "yes"}).status_code, 404)
        self.assertEqual(self.clients["pernik_manager"].post(f"/feedback/{self.C.pk}/", {"helpful": "yes"}).status_code, 302)
        self.assertTrue(GuideStat.objects.filter(guide=self.C, venue=self.pernik, helpful=1).exists())

    def test_panel_says_who_sees_it(self):
        html = self.html(self.editor.get("/manage/"))
        for text in ("Перник (служители и управител)", "Само управителите на Перник", "Само управителите на Перник, София – Младост"):
            self.assertIn(text, html)
        self.assertEqual(summary(self.E), "Перник, София – Младост (служители и управител)")
        self.assertContains(self.editor.get(self.B.url), "Вижда се от: <b>Перник (служители и управител)</b>")

    def test_edit_page_shows_the_choice(self):
        html = self.html(self.editor.get(f"/manage/{self.E.pk}/"))
        self.assertRegex(html, rf'name="staff_venues" value="{self.sah.pk}" data-staff checked')
        self.assertNotIn("data-manager checked", html)
        self.assertNotRegex(html, r'name="all_venues" data-all-venues checked')
        html = self.html(self.editor.get(f"/manage/{self.C.pk}/"))
        self.assertRegex(html, rf'name="manager_venues" value="{self.pernik.pk}" data-manager checked')
        html = self.html(self.editor.get("/manage/new/"))
        self.assertRegex(html, r'name="all_venues" data-all-venues checked')
        self.assertNotIn("Управителите на всички обекти", html)

    def test_edit_without_audience_is_refused(self):
        response, _ = self.save_post(self.editor, url=f"/manage/{self.E.pk}/", title="Два обекта", all_venues=None)
        self.assertEqual(response.status_code, 200)
        self.E.refresh_from_db()
        self.assertEqual(set(self.E.venues.all()), {self.sah, self.pernik})

    def test_archived_post_takes_its_new_audience_back_to_the_site(self):
        self.editor.post(f"/manage/{self.C.pk}/toggle/")
        self.save_post(self.editor, url=f"/manage/{self.C.pk}/", title=self.C.title, all_venues=None, staff_venues=[self.sah.pk])
        self.C.refresh_from_db()
        self.assertFalse(self.C.live)
        self.assertEqual((self.C.audience, list(self.C.venues.all())), ("staff", [self.sah]))
        self.editor.post(f"/manage/{self.C.pk}/toggle/")
        self.assertEqual(self.clients["mladost_staff"].get(self.C.url).status_code, 200)
        self.assertEqual(self.clients["pernik_manager"].get(self.C.url).status_code, 404)

    def test_deleting_a_venue(self):
        self.assertEqual({p.pk for p in posts_only_for(self.sah)}, set())
        boss = self.client_for(self.admin)
        sah_staff = self.clients["mladost_staff"]
        response = boss.post(f"/manage/venues/{self.sah.pk}/delete/", follow=True)
        self.assertContains(response, "заедно с потребителите му (2)")
        self.assertEqual(sah_staff.get("/").status_code, 302)  # its sessions are gone
        self.D.refresh_from_db()
        self.E.refresh_from_db()
        self.assertEqual(list(self.E.venues.all()), [self.pernik])
        self.assertEqual(self.clients["pernik_staff"].get(self.E.url).status_code, 200)
        self.editor.post(f"/manage/{self.E.pk}/toggle/")
        self.editor.post(f"/manage/{self.E.pk}/toggle/")  # an old revision naming the deleted venue publishes
        self.assertTrue(GuidePage.objects.get(pk=self.E.pk).live)

    def test_post_only_for_a_deleted_venue_reaches_nobody(self):
        only = self.post("Само Младост", {"staff_venues": [self.sah.pk]})
        self.assertEqual([p.pk for p in posts_only_for(self.sah)], [only.pk])
        self.client_for(self.admin).post(f"/manage/venues/{self.sah.pk}/delete/")
        only.refresh_from_db()
        self.assertEqual(summary(only), "Никой (обектите са изтрити)")
        self.assertEqual(self.clients["pernik_manager"].get(only.url).status_code, 404)

    def test_frequent_searches_come_only_from_staff(self):
        staff, manager = self.clients["pernik_staff"], self.clients["pernik_manager"]
        for _ in range(3):
            staff.get("/search/?q=тайнаxyz")
            manager.get("/search/?q=управителскатайна")

        def chips(client):
            return re.findall(r'class="chip" href="[^"]*">([^<]*)<', self.html(client.get("/")))

        self.assertIn("тайнаxyz", chips(staff))
        for client in (staff, manager, self.clients["mladost_staff"]):
            self.assertNotIn("управителскатайна", chips(client))
        self.assertTrue(SearchStat.objects.filter(query="управителскатайна", venue=self.pernik, role="manager").exists())

    def test_two_staff_accounts_of_a_venue_see_the_same(self):
        from guides.audience import visible_guides
        from venues.access import create_account

        second = create_account("pernik_staff2", self.pernik, "staff", PASSWORD)
        self.assertEqual(set(visible_guides(second)), set(visible_guides(self.pernik_staff)))

    def test_moving_an_account_changes_what_it_sees_at_once(self):
        client = Client()
        client.post("/login/", {"username": "pernik_staff", "password": PASSWORD})
        boss = self.client_for(self.admin)
        boss.post(f"/manage/users/{self.pernik_staff.pk}/", {"username": "pernik_staff", "role": "manager", "venue": self.pernik.pk})
        self.assertEqual(client.get(self.C.url).status_code, 200)
        boss.post(f"/manage/users/{self.pernik_staff.pk}/", {"username": "pernik_staff", "role": "staff", "venue": self.sah.pk})
        self.assertEqual(client.get(self.B.url).status_code, 404)
        self.assertEqual(client.get(self.E.url).status_code, 200)


class SearchTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)

    def test_word_endings_and_title_first(self):
        self.save_post(self.editor, title="Каса", body=json.dumps([{"type": "text", "html": "<p>принтерът до касата</p>"}]))
        self.save_post(self.editor, title="Принтерът не печата")
        html = self.html(self.staff.get("/search/?q=ПРИНТЕР"))
        self.assertIn("Намерени: 2", html)
        self.assertLess(html.find("Принтерът не печата"), html.find("Каса</h3>"))

    def test_every_word_must_match(self):
        self.save_post(self.editor, title="Принтерът не печата")
        self.assertContains(self.staff.get("/search/?q=принтер+печата"), "Намерени: 1")
        self.assertContains(self.staff.get("/search/?q=принтер+скенер"), "Няма резултати")

    def test_odd_queries(self):
        self.save_post(self.editor, title="100% отстъпка")
        self.assertContains(self.staff.get("/search/?q=100%25"), "Намерени: 1")
        self.assertEqual(self.staff.get("/search/?q=").status_code, 200)
        self.assertEqual(self.staff.get("/search/?q=" + "дума " * 2000).status_code, 200)  # cut, not hundreds of filters
        self.assertEqual(self.staff.get("/search/?q=x&page=999").status_code, 200)
        self.assertEqual(self.staff.get("/search/?q=x&page=abc").status_code, 200)
        self.staff.get("/search/?q=" + "я" * 300)
        self.assertTrue(all(len(s.query) <= 100 for s in SearchStat.objects.all()))


class ForgivingSearchTests(InfoHubTestCase):
    """Wrong keyboard layout, Bulgarian in Latin letters and typos still find the post."""

    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.staff = self.client_for(self.pernik_staff)
        self.save_post(self.editor, title="Принтерът не печата")
        self.save_post(self.editor, title="Outlook не праща поща")

    def found(self, query):
        html = self.html(self.staff.get("/search/", {"q": query}))
        return "Принтерът не печата" in html, "Outlook не праща поща" in html, html

    def test_typed_in_another_layout_or_in_latin(self):
        for query in ("printer", "ghbynth", "m,rkje,", "PRINTER"):  # phonetic = Latin, ЙЦУКЕН, БДС
            self.assertEqual(self.found(query)[:2], (True, False), query)
        self.assertEqual(self.found("щгедщщл")[:2], (False, True))  # "outlook" on the phonetic layout
        self.assertIn("Показани са резултати за „<strong>принтер</strong>“", self.found("printer")[2])

    def test_typos(self):
        for query in ("принетр", "пирнтер", "принтерат"):
            self.assertTrue(self.found(query)[0], query)
        self.assertFalse(self.found("прн")[0])  # short words: no guessing
        self.assertIn("Няма резултати", self.found("скенер")[2])

    def test_what_was_typed_wins(self):
        html = self.found("принтер")[2]
        self.assertNotIn("Показани са резултати за", html)
        self.assertIn("Намерени: 1", html)

    def test_guesses_come_only_from_posts_the_viewer_may_see(self):
        self.save_post(self.editor, title="Тайна инвентаризация", all_venues=None, manager_venues=[self.pernik.pk])
        self.assertIn("Няма резултати", self.found("инвентаризацйа")[2])
        manager = self.html(self.client_for(self.pernik_manager).get("/search/", {"q": "инвентаризацйа"}))
        self.assertIn("Тайна инвентаризация", manager)

    def test_every_word_still_has_to_match(self):
        self.assertTrue(self.found("printer pechata")[0])
        self.assertFalse(self.found("printer skener")[0])


class CategoryPageTests(InfoHubTestCase):
    def test_category_page_lists_only_what_the_viewer_may_see(self):
        editor = self.client_for(self.marketing_editor)
        editor.post("/manage/categories/", {"title": "Промоции", "department": self.marketing.pk})
        from guides.models import CategoryPage

        category = CategoryPage.objects.get(title="Промоции")
        self.save_post(editor, title="Промоция за всички", place=category.pk)
        self.save_post(editor, title="Промоция за Младост", place=category.pk, all_venues=None, staff_venues=[self.sah.pk])
        html = self.html(self.client_for(self.pernik_staff).get(category.url))
        self.assertIn("Промоция за всички", html)
        self.assertNotIn("Промоция за Младост", html)
        self.assertIn("Промоция за Младост", self.html(self.client_for(self.mladost_staff).get(category.url)))
        department = self.html(self.client_for(self.pernik_staff).get("/marketing/?type=news"))
        self.assertIn("Промоции", department)
        self.assertEqual(self.client_for(self.pernik_staff).get("/marketing/?type=xyz&page=abc").status_code, 200)
