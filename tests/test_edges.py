"""Edge cases across the site: hostile input, odd requests, rarely used paths."""

import json
from urllib.parse import unquote

from django.test import Client

from guides.audience import summary
from guides.models import DepartmentPage, GuidePage
from venues.models import Venue

from .base import PASSWORD, InfoHubTestCase

HOSTILE = '<script>alert(1)</script><img src=x onerror=alert(2)>'


class HostileTextTests(InfoHubTestCase):
    """Whatever an editor types is shown as text, never run as code."""

    def test_titles_captions_and_headings_are_escaped_everywhere(self):
        boss = self.client_for(self.admin)
        body = [
            {"type": "heading", "text": HOSTILE},
            {"type": "step", "title": HOSTILE, "html": "<p>текст</p>", "images": []},
            {"type": "note", "style": "info", "html": f"<p>{HOSTILE}</p>"},
        ]
        response, guide = self.save_post(boss, title="Опит " + HOSTILE, summary=HOSTILE, body=json.dumps(body), needs_ack="on")
        self.assertEqual(response.status_code, 302)
        staff = self.client_for(self.pernik_staff)
        pages = {
            "home": staff.get("/"), "guide": staff.get(guide.url), "search": staff.get("/search/?q=опит"),
            "department": staff.get(self.marketing.url), "panel": boss.get("/manage/"), "editor": boss.get(f"/manage/{guide.pk}/"),
            "reads": boss.get(f"/manage/{guide.pk}/reads/"), "preview": boss.get(f"/manage/{guide.pk}/preview/"),
        }
        for name, page in pages.items():
            html = self.html(page)
            self.assertEqual(page.status_code, 200, name)
            self.assertNotIn("<script>alert(1)", html, name)
            self.assertNotIn("<img src=x", html, name)
        self.assertIn("&lt;script&gt;", self.html(pages["guide"]))
        # The editor gets the text back unchanged as data, so it can be fixed.
        self.assertIn(HOSTILE, json.dumps(self.editor_config(pages["editor"]), ensure_ascii=False))

    def test_hostile_venue_and_department_names(self):
        boss = self.client_for(self.admin)
        boss.post("/manage/venues/", {"name": "Пловдив – <b>Център</b>"})
        venue = Venue.objects.get(name__contains="Център")
        boss.post("/manage/departments/", {"title": "<i>Финанси</i>", "slug": "finance", "description": HOSTILE, "color": "blue", "icon": "info"})
        for url in ("/manage/venues/", "/manage/departments/", "/manage/users/", "/manage/new/", "/"):
            html = self.html(boss.get(url))
            self.assertNotIn("<b>Център</b>", html, url)
            self.assertNotIn("<i>Финанси</i>", html, url)
            self.assertNotIn("<script>alert(1)", html, url)
        self.assertTrue(venue.pk)


class LoginRedirectTests(InfoHubTestCase):
    def login(self, next_url):
        return Client().post(f"/login/?next={next_url}", {"username": "pernik_staff", "password": PASSWORD})

    def test_next_to_another_site_is_ignored(self):
        for target in ("https://evil.example/", "//evil.example/", "/\\evil.example/", "javascript:alert(1)"):
            location = self.login(target)["Location"]
            self.assertTrue(location.startswith("/") and not location.startswith(("//", "/\\")), (target, location))

    def test_next_inside_the_site_is_kept(self):
        self.assertEqual(unquote(self.login("/search/?q=принтер")["Location"]), "/search/?q=принтер")

    def test_django_admin_is_gone(self):
        self.assertEqual(self.client_for(self.admin).get("/django-admin/").status_code, 404)
        self.assertRedirects(Client().get("/django-admin/login/"), "/login/?next=/django-admin/login/", fetch_redirect_response=False)


class OddRequestsTests(InfoHubTestCase):
    def test_search_with_odd_queries(self):
        self.save_post(self.client_for(self.admin), title="Принтер 100% готов")
        staff = self.client_for(self.pernik_staff)
        for query in ("%", "_", "'", '"', "\\", "100%", "😀", " ", "a" * 5000, "<script>", "принтер' OR 1=1 --"):
            self.assertEqual(staff.get("/search/", {"q": query}).status_code, 200, query[:20])
        self.assertContains(staff.get("/search/", {"q": "100%"}), "Принтер 100% готов")
        self.assertNotContains(staff.get("/search/", {"q": "_"}), "Принтер 100% готов")

    def test_unknown_ids_are_404(self):
        boss = self.client_for(self.admin)
        for url in ("/manage/999999/", "/manage/999999/reads/", "/manage/999999/preview/", "/manage/departments/999999/",
                    "/manage/users/999999/", "/manage/venues/999999/"):
            self.assertEqual(boss.get(url).status_code, 404, url)
        for url in ("/manage/999999/toggle/", "/manage/999999/delete/", "/manage/departments/999999/move/",
                    "/read/999999/", "/feedback/999999/"):
            self.assertEqual(boss.post(url).status_code, 404, url)

    def test_too_long_title_and_summary_are_refused(self):
        boss = self.client_for(self.admin)
        self.assertContains(self.save_post(boss, title="я" * 256)[0], "Заглавието е твърде дълго")
        self.assertContains(self.save_post(boss, title="Кратко", summary="я" * 301)[0], "Краткото описание е до 300 знака")
        self.assertFalse(GuidePage.objects.filter(title="Кратко").exists())

    def test_feedback_without_javascript_returns_to_the_post(self):
        _, guide = self.save_post(self.client_for(self.admin), title="Без JS")
        response = self.client_for(self.pernik_staff).post(f"/feedback/{guide.pk}/", {"helpful": "yes"})
        self.assertEqual(response["Location"], f"{guide.url}?thanks=yes#feedback")

    def test_panel_filter_only_live(self):
        boss = self.client_for(self.admin)
        self.save_post(boss, title="На сайта")
        self.save_post(boss, title="Чернова", action="draft")
        html = self.html(boss.get("/manage/?status=active")).split('<table class="guide-table">')[1]
        self.assertIn("На сайта", html)
        self.assertNotIn("Чернова", html)

    def test_stats_for_one_department(self):
        self.assertEqual(self.client_for(self.admin).get(f"/manage/stats/?department={self.marketing.pk}").status_code, 200)


class SectionsTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.boss = self.client_for(self.admin)

    def test_edit_page_and_name_checks(self):
        page = self.html(self.boss.get(f"/manage/departments/{self.marketing.pk}/"))
        self.assertIn('value="Маркетинг"', page)
        self.assertContains(self.boss.post(f"/manage/departments/{self.marketing.pk}/",
                                           {"title": "КАЗИНО СИСТЕМА", "description": "", "color": "blue", "icon": "info"}),
                            "Вече има раздел с това име")
        self.boss.post(f"/manage/departments/{self.marketing.pk}/", {"title": "МАРКЕТИНГ", "description": "", "color": "blue", "icon": "info"})
        self.assertEqual(DepartmentPage.objects.get(pk=self.marketing.pk).title, "МАРКЕТИНГ")  # its own name in other case is fine

    def test_new_section_goes_last_and_can_move_to_the_top(self):
        self.boss.post("/manage/departments/", {"title": "Финанси", "slug": "finance", "description": "", "color": "blue", "icon": "info"})
        finance = DepartmentPage.objects.get(slug="finance")
        self.assertEqual(DepartmentPage.objects.order_by("path").last(), finance)
        for _ in range(10):  # more clicks than needed: stops at the top
            self.boss.post(f"/manage/departments/{finance.pk}/move/", {"direction": "up"})
        self.assertEqual([d.slug for d in DepartmentPage.objects.order_by("path")], ["finance", "it", "cms", "marketing", "hr"])
        html = self.html(self.boss.get("/manage/departments/"))
        self.assertEqual(html.count("disabled>↑"), 1)
        self.assertEqual(html.count("disabled>↓"), 1)

    def test_moving_keeps_posts_editors_and_addresses(self):
        _, guide = self.save_post(self.client_for(self.marketing_editor), title="Промо")
        self.boss.post(f"/manage/departments/{self.marketing.pk}/move/", {"direction": "up"})
        guide.refresh_from_db()
        self.assertEqual(guide.url, "/marketing/promo/")
        self.assertEqual(self.client_for(self.pernik_staff).get(guide.url).status_code, 200)
        self.assertEqual(self.save_post(self.client_for(self.marketing_editor), title="Второ")[0].status_code, 302)


class AdminFormsTests(InfoHubTestCase):
    def test_wagtail_user_edit_and_account_without_names(self):
        boss = self.client_for(self.admin)
        self.assertEqual(boss.get(f"/admin/users/edit/{self.marketing_editor.pk}/").status_code, 200)
        self.assertEqual(boss.get("/admin/account/").status_code, 200)


class SummaryTests(InfoHubTestCase):
    def test_many_venues_are_counted_not_listed(self):
        venues = [Venue.objects.create(name=f"Обект {i}") for i in range(6)]
        _, guide = self.save_post(self.client_for(self.admin), title="За много", all_venues=None,
                                  staff_venues=[v.pk for v in venues])
        self.assertIn("6 обекта", summary(guide))


class ModelAndReportEdgeTests(InfoHubTestCase):
    def test_a_post_for_chosen_venues_needs_a_venue_in_the_admin_too(self):
        from django.core.exceptions import ValidationError

        from guides.models import AUDIENCE_STAFF, GuidePage

        _, guide = self.save_post(self.client_for(self.marketing_editor), title="Без обект")
        guide = GuidePage.objects.get(pk=guide.pk)
        guide.audience = AUDIENCE_STAFF
        with self.assertRaisesMessage(ValidationError, "Изберете поне един обект"):
            guide.clean()

    def test_a_search_that_found_something_later_is_no_longer_failed(self):
        import datetime

        from stats.models import SearchStat
        from stats.reports import failed_searches

        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        rows = [("щжюзъ", yesterday, 0), ("щжюзъ", today, 3),  # found later: not a gap any more
                ("ьъюящ", yesterday, 2), ("ьъюящ", today, 0)]  # found before, nothing now: a gap
        for query, day, results in rows:
            SearchStat.objects.create(query=query, venue=self.pernik, role="staff", day=day, count=1, results=results)
        self.assertEqual([e["query"] for e in failed_searches(venue=self.pernik)], ["ьъюящ"])
