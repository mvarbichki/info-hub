"""„Виж като обект“: an editor sees the site exactly as a venue account does, and nothing is recorded."""

from django.contrib.auth.models import User

from stats.models import Ack, GuideStat, SearchStat, Seen, Vote
from venues.models import VenueAccount
from venues.viewas import SESSION_KEY

from . import test_audience
from .base import InfoHubTestCase


def viewing_as(test, user, editor=None):
    """A client of the editor (default marketing) looking at the site as `user`'s venue account."""
    client = test.client_for(editor or test.marketing_editor)
    account = VenueAccount.objects.get(user=user)
    response = client.post("/manage/view-as/", {"account": account.pk, "next": "/marketing/"})
    test.assertRedirects(response, "/marketing/", fetch_redirect_response=False)
    return client


class ViewAsVisibilityTests(test_audience.VisibilityTests):
    """The whole who-sees-what suite again, but each venue is looked at by an editor through
    „Виж като обект“ instead of being logged in itself: the results must be the same."""

    def setUp(self):
        super().setUp()
        self.clients = {
            "pernik_staff": viewing_as(self, self.pernik_staff),
            "pernik_manager": viewing_as(self, self.pernik_manager),
            "mladost_staff": viewing_as(self, self.mladost_staff),
            "mladost_manager": viewing_as(self, self.mladost_manager),
            "training": viewing_as(self, self.training_staff),
        }

    # Three of the inherited tests check things that, by design, a look never does:

    def test_feedback_only_on_own_posts(self):
        """A vote is refused while looking (the real account's own vote is in VisibilityTests)."""
        for post in (self.A, self.C):
            self.assertEqual(self.clients["pernik_manager"].post(f"/feedback/{post.pk}/", {"helpful": "yes"}).status_code, 403)
        self.assertFalse(GuideStat.objects.exists())

    def test_frequent_searches_come_only_from_staff(self):
        """The chips come from the venues' real searches; searching while looking adds none."""
        real = self.client_for(self.pernik_staff)
        for _ in range(3):
            real.get("/search/?q=тайнаxyz")
            self.clients["pernik_staff"].get("/search/?q=другоxyz")
        home = self.html(self.clients["pernik_staff"].get("/"))
        self.assertIn('">тайнаxyz<', home)
        self.assertNotIn("другоxyz", home)
        self.assertFalse(SearchStat.objects.filter(query="другоxyz").exists())

    def test_deleting_a_venue(self):
        """Its accounts are gone, so looking through one of them ends: the editor's own site again."""
        looking = self.clients["mladost_staff"]
        self.client_for(self.admin).post(f"/manage/venues/{self.sah.pk}/delete/")
        home = looking.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertNotContains(home, "manage-bar--view-as")
        self.assertContains(home, "Като редактор виждате всички публикации")

    def test_the_same_pages_as_the_account_itself(self):
        real = self.client_for(self.pernik_manager)
        seen_by = viewing_as(self, self.pernik_manager, editor=self.admin)
        for url in ["/", "/marketing/", "/search/?q=тайнаxyz"] + [p.url for p in self.everyone]:
            with self.subTest(url=url):
                mine, theirs = real.get(url), seen_by.get(url)
                self.assertEqual(mine.status_code, theirs.status_code)
                if mine.status_code == 200:
                    for post in self.everyone:
                        self.assertEqual(post.title in self.html(mine), post.title in self.html(theirs), post.title)

    def test_nothing_is_recorded(self):
        def counts():
            return [m.objects.count() for m in (Seen, GuideStat, SearchStat, Vote, Ack)]

        before = counts()
        for client in self.clients.values():
            for url in ("/", "/marketing/", "/search/?q=тайнаxyz", "/search/?q=нищоняма"):
                client.get(url)
            for post in self.everyone:
                client.get(post.url)
                self.assertEqual(client.post(f"/feedback/{post.pk}/", {"helpful": "yes"}).status_code, 403)
                no = client.post(f"/feedback/{post.pk}/", {"helpful": "no", "reason": "липсва снимка"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                self.assertEqual(no.status_code, 403)
                self.assertIn("Преглед като обект", no.json()["error"])
                self.assertEqual(client.post(f"/read/{post.pk}/").status_code, 403)
        self.assertEqual(counts(), before)


class ViewAsTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        _, self.post = self.save_post(
            self.editor, title="Инвентаризация", all_venues=None, manager_venues=[self.pernik.pk], needs_ack="on",
        )

    def test_the_choice_page(self):
        page = self.html(self.editor.get("/manage/view-as/?next=/marketing/"))
        self.assertIn('class="manage-header"', page)
        self.assertIn("Перник – управител (pernik_manager)", page)
        self.assertIn("Обучение – служители (staff)", page)
        self.assertIn('name="next" value="/marketing/"', page)
        response = self.editor.post("/manage/view-as/", {"account": "x"})
        self.assertContains(response, "Изберете обект и потребител")
        response = self.editor.post("/manage/view-as/", {"account": "999999"})
        self.assertContains(response, "Изберете обект и потребител")
        self.assertNotIn(SESSION_KEY, self.editor.session)

    def test_next_never_leaves_the_site(self):
        account = VenueAccount.objects.get(user=self.pernik_staff)
        for bad in ("https://evil.example/", "//evil.example/", "/manage/users/", "/admin/", "/login/", ""):
            with self.subTest(next=bad):
                response = self.editor.post("/manage/view-as/", {"account": account.pk, "next": bad})
                self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_the_bar_while_looking(self):
        client = viewing_as(self, self.pernik_manager)
        html = self.html(client.get(self.post.url))
        self.assertIn("manage-bar--view-as", html)
        self.assertIn("Виждате сайта като: <b>Перник – управител (pernik_manager)</b>", html)
        self.assertIn("Изход (marketing)", html)
        self.assertIn("Край на прегледа", html)
        self.assertNotIn("Изход (pernik_manager)", html)   # the venue's own logout isn't offered
        self.assertNotIn("Редактирай тази публикация", html)  # the venue's page, not the editor's
        self.assertIn("Само за управители", html)
        # the manager's buttons are there, but only to look at
        self.assertRegex(html, r'<button type="submit" class="button-primary" disabled[^>]*>Прочетох</button>')
        self.assertRegex(html, r'value="yes" class="button-secondary" disabled')
        self.assertIn("Потвърдете прочитане", self.html(client.get("/")))

    def test_a_page_the_account_does_not_see(self):
        client = viewing_as(self, self.pernik_staff)
        response = client.get(self.post.url)
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Перник – служители (pernik_staff)</b> не вижда тази страница", status_code=404)

    def test_management_stays_the_editors_and_the_end(self):
        client = viewing_as(self, self.pernik_staff)
        panel = client.get("/manage/")
        self.assertEqual(panel.status_code, 200)
        self.assertContains(panel, "Сайтът се показва като: <b>Перник – служители (pernik_staff)</b>")
        self.assertContains(panel, "Инвентаризация")  # the editor's own list
        self.assertEqual(client.get(f"/manage/{self.post.pk}/").status_code, 200)
        # a post saved meanwhile is saved by the editor, as usual
        _, saved = self.save_post(client, title="Нова от редактора")
        self.assertTrue(saved.live)
        response = client.post("/manage/view-as/end/", {"next": self.post.url})
        self.assertRedirects(response, self.post.url, fetch_redirect_response=False)
        page = self.html(client.get(self.post.url))
        self.assertNotIn("manage-bar--view-as", page)
        self.assertIn("Като редактор виждате всички публикации", page)
        self.assertIn("Виж като обект…", page)
        self.assertEqual(client.post("/manage/view-as/end/", {"next": "https://evil.example/"})["Location"], "/")

    def test_only_editors(self):
        account = VenueAccount.objects.get(user=self.pernik_manager)
        manager = self.client_for(self.pernik_manager)
        response = manager.post("/manage/view-as/", {"account": account.pk})
        self.assertTrue(response["Location"].startswith("/login/"))
        self.assertNotIn(SESSION_KEY, manager.session)
        # a venue account with the key in its session (cannot happen) still sees only its own
        staff = self.client_for(self.pernik_staff)
        session = staff.session
        session[SESSION_KEY] = account.pk
        session.save()
        self.assertEqual(staff.get(self.post.url).status_code, 404)
        self.assertNotIn(SESSION_KEY, staff.session)  # and it is dropped

    def test_ends_by_itself_when_the_account_is_gone(self):
        client = viewing_as(self, self.pernik_manager)
        User.objects.filter(pk=self.pernik_manager.pk).delete()
        page = self.html(client.get("/"))
        self.assertNotIn("manage-bar--view-as", page)
        self.assertNotIn(SESSION_KEY, client.session)

    def test_logout_logs_out_the_editor(self):
        client = viewing_as(self, self.pernik_staff)
        client.post("/manage/logout/")
        self.assertTrue(client.get("/")["Location"].startswith("/login/"))
        self.assertNotIn(SESSION_KEY, client.session)
