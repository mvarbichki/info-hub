"""Logins, who may open what, the login throttle, venue passwords, logout and expired forms."""

from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from dashboard.access import create_editor
from dashboard.models import must_change_password

from guides.models import GuidePage

from .base import PASSWORD, InfoHubTestCase


class AnonymousTests(InfoHubTestCase):
    def test_every_page_needs_a_login(self):
        anon = Client()
        for url in ("/", "/marketing/", "/search/?q=x", "/manage/", "/manage/stats/", "/media/images/x.png"):
            response = anon.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/login/"), url)

    def test_robots_txt_is_public_and_disallows_all(self):
        response = Client().get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Disallow: /", response.content)

    def test_login_page_is_public_and_not_indexed(self):
        response = Client().get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="robots" content="noindex')
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotContains(response, "site-nav")  # no department menu before login

    def test_old_login_addresses_lead_to_the_one_login(self):
        for url in ("/manage/login/?next=/manage/", "/admin/login/?next=/admin/"):
            response = Client().get(url)
            self.assertIn(response.status_code, (301, 302))
            self.assertTrue(response["Location"].startswith("/login/") and "next=" in response["Location"], url)


class LoginTests(InfoHubTestCase):
    def login(self, username, password):
        client = Client()
        return client, client.post("/login/", {"username": username, "password": password})

    def test_superuser_and_editors_land_in_the_panel(self):
        for username, password in (("admin", "Admin-pass-2026"), ("marketing", "marketing-Pass-2026")):
            client, response = self.login(username, password)
            self.assertRedirects(response, "/manage/", fetch_redirect_response=False)
            self.assertLess(client.session.get_expiry_age(), 30 * 24 * 3600)

    def test_venue_accounts_land_on_the_site_for_a_year(self):
        for user in (self.pernik_staff, self.pernik_manager):
            client, response = self.login(user.username, PASSWORD)
            self.assertRedirects(response, "/", fetch_redirect_response=False)
            self.assertGreater(client.session.get_expiry_age(), 360 * 24 * 3600)
            home = client.get("/")
            self.assertContains(home, f"Изход ({user.username})</button>")
            self.assertNotContains(home, "manage-bar")

    def test_login_names_ignore_case_and_spaces(self):
        _, response = self.login("  Pernik_STAFF ", PASSWORD)
        self.assertEqual(response.status_code, 302)

    def test_wrong_password_and_account_without_password(self):
        _, response = self.login("pernik_staff", "wrong")
        self.assertContains(response, "Грешно")
        _, response = self.login("manager", "anything")  # training manager: no password set
        self.assertEqual(response.status_code, 200)

    def test_new_editor_must_change_the_temporary_password(self):
        editor = create_editor("finance", self.it)
        client, response = self.login("finance", "finance")
        self.assertEqual(response.status_code, 302)
        response = client.get("/manage/")
        self.assertRedirects(response, "/manage/password/", fetch_redirect_response=False)
        self.assertEqual(client.get("/manage/password/").status_code, 200)
        response = client.post("/manage/password/", {
            "old_password": "finance", "new_password1": "Novo-Finance-2026", "new_password2": "Novo-Finance-2026",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(must_change_password(editor))
        self.assertEqual(client.get("/manage/").status_code, 200)

    def test_logged_in_user_is_sent_on_unless_a_page_sent_them_here(self):
        staff = self.client_for(self.pernik_staff)
        self.assertEqual(staff.get("/login/").status_code, 302)
        response = staff.get("/login/?next=/manage/")
        self.assertContains(response, 'name="password"')
        self.assertContains(response, "Влезли сте като")

    def test_logout_everywhere_goes_to_the_login_page(self):
        editor = self.client_for(self.marketing_editor)
        response = editor.post("/manage/logout/", follow=True)
        self.assertTrue(response.redirect_chain[-1][0].startswith("/login/"))
        self.assertContains(response, "Излязохте успешно")
        response = self.client_for(self.admin).post("/admin/logout/")
        self.assertTrue(response["Location"].startswith("/login/"))

    def test_a_double_logout_and_the_next_login(self):
        """VM 2026-10-31: „Изход“ sent twice; the second logout came from someone already logged out
        and went to /login/?next=/manage/logout/, so after the next login the browser opened the logout
        address and showed an empty 405 page."""
        client, _ = self.login("pernik_staff", PASSWORD)
        self.assertRedirects(client.post("/manage/logout/"), "/login/", fetch_redirect_response=False)
        second = client.post("/manage/logout/")
        self.assertRedirects(second, "/login/", fetch_redirect_response=False)  # no "next"
        page = client.get("/login/")
        self.assertEqual(page.content.decode().count("Излязохте успешно"), 1)
        response = client.post("/login/", {"username": "pernik_manager", "password": PASSWORD}, follow=True)
        self.assertEqual(response.redirect_chain, [("/", 302)])
        self.assertContains(response, "Изход (pernik_manager)")

    def test_the_logout_address_opened_as_a_page(self):
        manager = self.client_for(self.pernik_manager)
        self.assertRedirects(manager.get("/manage/logout/"), "/login/", fetch_redirect_response=False)
        self.assertContains(manager.get("/"), "Изход (pernik_manager)")  # a visit logs nobody out
        self.assertRedirects(Client().get("/manage/logout/"), "/login/", fetch_redirect_response=False)
        # an old "log in, then log out" link: the login page drops it
        self.assertRedirects(Client().get("/login/?next=/manage/logout/"), "/login/", fetch_redirect_response=False)
        client = Client()
        response = client.post("/login/?next=/manage/logout/", {"username": "pernik_manager", "password": PASSWORD}, follow=True)
        self.assertEqual(response.redirect_chain[-1], ("/", 302))
        self.assertContains(response, "Изход (pernik_manager)")


class VenueAccountLimitsTests(InfoHubTestCase):
    def test_venue_accounts_have_no_panel_and_no_admin(self):
        staff = self.client_for(self.pernik_staff)
        for url in ("/manage/", "/manage/new/", "/manage/venues/", "/manage/users/", "/manage/stats/"):
            response = staff.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response["Location"].startswith("/login/?next="), url)
        self.assertIn(staff.get("/admin/").status_code, (302, 403))
        self.assertEqual(staff.post("/manage/upload/", {"kind": "image"}).status_code, 302)

    def test_venue_accounts_cannot_change_or_reset_their_password(self):
        for user in (self.pernik_staff, self.pernik_manager):
            client = self.client_for(user)
            for url in ("/manage/password/", "/admin/account/", "/admin/account/change_password/", "/admin/password_reset/"):
                response = client.get(url)
                self.assertIn(response.status_code, (302, 403, 404), url)
                self.assertNotContains(response, 'name="new_password1"', status_code=response.status_code)
            new = {"old_password": PASSWORD, "new_password1": "Nova-Parola-2026x", "new_password2": "Nova-Parola-2026x"}
            self.assertEqual(client.post("/manage/password/", new).status_code, 403)
            client.post("/admin/account/", {f"password-{k}": v for k, v in new.items()})
            user.refresh_from_db()
            self.assertTrue(user.check_password(PASSWORD))
            self.assertNotContains(client.get("/"), "/manage/password/")
        self.assertIn(Client().get("/admin/password_reset/").status_code, (302, 404))

    def test_stopped_venue_logs_its_pcs_out_and_lets_them_back(self):
        boss = self.client_for(self.admin)
        staff = Client()
        staff.post("/login/", {"username": "pernik_staff", "password": PASSWORD})
        boss.post(f"/manage/venues/{self.pernik.pk}/toggle/")
        self.assertEqual(staff.get("/").status_code, 302)
        response = Client().post("/login/", {"username": "pernik_manager", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertContains(boss.get("/manage/users/?role=staff"), "Обектът е спрян")
        boss.post(f"/manage/venues/{self.pernik.pk}/toggle/")
        self.assertEqual(staff.get("/").status_code, 200)  # the same session works again

    def test_account_stopped_on_its_own_stays_stopped(self):
        boss = self.client_for(self.admin)
        boss.post(f"/manage/users/{self.pernik_manager.pk}/toggle/")
        boss.post(f"/manage/venues/{self.pernik.pk}/toggle/")
        boss.post(f"/manage/venues/{self.pernik.pk}/toggle/")
        response = Client().post("/login/", {"username": "pernik_manager", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.get(pk=self.pernik_manager.pk).is_active)

    def test_new_password_logs_the_account_out(self):
        staff = Client()
        staff.post("/login/", {"username": "pernik_staff", "password": PASSWORD})
        boss = self.client_for(self.admin)
        response = boss.post(f"/manage/users/{self.pernik_staff.pk}/password/", {"new_password1": "1234", "new_password2": "1234"})
        self.assertContains(response, "field-error")  # weak password refused
        boss.post(f"/manage/users/{self.pernik_staff.pk}/password/", {"new_password1": "Novo-Parola-88", "new_password2": "Novo-Parola-88"})
        self.assertEqual(staff.get("/").status_code, 302)
        staff.post("/login/", {"username": "pernik_staff", "password": "Novo-Parola-88"})
        self.assertEqual(staff.get("/").status_code, 200)


class ThrottleTests(InfoHubTestCase):
    def fail(self, client, times=10, **extra):
        for _ in range(times):
            client.post("/login/", {"username": "pernik_staff", "password": "wrong"}, **extra)

    def test_eleventh_attempt_is_locked_even_with_the_right_password(self):
        client = Client()
        self.fail(client)
        response = client.post("/login/", {"username": "pernik_staff", "password": PASSWORD})
        self.assertContains(response, "Твърде много")

    def test_other_addresses_are_not_locked(self):
        self.fail(Client(), REMOTE_ADDR="10.0.0.1")
        response = Client().post("/login/", {"username": "pernik_staff", "password": PASSWORD}, REMOTE_ADDR="10.0.0.2")
        self.assertEqual(response.status_code, 302)

    @override_settings(INFOHUB_CLIENT_IP_HEADER="HTTP_X_REAL_IP")
    def test_behind_the_proxy_each_visitor_counts_on_their_own(self):
        # Every request comes from the proxy (same REMOTE_ADDR); the proxy says who the visitor is.
        self.fail(Client(), REMOTE_ADDR="172.18.0.5", HTTP_X_REAL_IP="85.1.1.1")
        locked = Client().post("/login/", {"username": "pernik_staff", "password": PASSWORD}, REMOTE_ADDR="172.18.0.5", HTTP_X_REAL_IP="85.1.1.1")
        self.assertContains(locked, "Твърде много")
        other = Client().post("/login/", {"username": "pernik_staff", "password": PASSWORD}, REMOTE_ADDR="172.18.0.5", HTTP_X_REAL_IP="85.2.2.2")
        self.assertEqual(other.status_code, 302)

    def test_without_a_proxy_the_header_is_ignored(self):
        # Nobody can escape the lock by sending a made-up X-Real-IP.
        self.fail(Client(), HTTP_X_REAL_IP="1.1.1.1")
        response = Client().post("/login/", {"username": "pernik_staff", "password": PASSWORD}, HTTP_X_REAL_IP="2.2.2.2")
        self.assertContains(response, "Твърде много")


class ExpiredFormTests(InfoHubTestCase):
    def test_expired_token_gets_a_bulgarian_page_and_the_cookie_token_works(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.marketing_editor)
        response = strict.post("/manage/new/", self.post_data())
        self.assertContains(response, "Страницата е изтекла и нищо не е запазено", status_code=403)
        strict.get("/manage/new/")
        token = strict.cookies["csrftoken"].value
        response = strict.post("/manage/new/", {**self.post_data(title="С бисквитката"), "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)

    def test_saving_while_logged_out_explains_what_to_do(self):
        anon = Client()
        response = anon.post("/manage/new/", self.post_data(), follow=True)
        self.assertContains(response, "тя не е запазена")
        self.assertContains(response, "Назад")
        self.assertContains(anon.get("/login/?next=/manage/12/"), "тя не е запазена")
        self.assertNotContains(anon.get("/login/?next=/manage/stats/"), "тя не е запазена")


class BrowserHabitsTests(InfoHubTestCase):
    """What browsers and people commonly do: a button pressed after the session ended, two tabs,
    an old page, the Back button after „Изход“."""

    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        _, self.rules = self.save_post(self.editor, title="Правила", needs_ack="on")

    def logged_out_post(self, url, referer=None):
        client = Client()
        extra = {"HTTP_REFERER": referer} if referer else {}
        return client, client.post(url, **extra)

    def test_a_button_after_the_session_ended_comes_back_to_its_page(self):
        page = f"http://testserver{self.rules.url}"
        client, response = self.logged_out_post(f"/read/{self.rules.pk}/", page)
        self.assertRedirects(response, f"/login/?next={self.rules.url}", fetch_redirect_response=False)
        response = client.post(response["Location"], {"username": "pernik_manager", "password": PASSWORD}, follow=True)
        self.assertEqual(response.redirect_chain, [(self.rules.url, 302)])
        self.assertContains(response, ">Прочетох и запознах екипа</button>")  # pressed again on purpose
        # a panel button with the list's filter
        client, response = self.logged_out_post(f"/manage/{self.rules.pk}/toggle/", "http://testserver/manage/?status=live")
        self.assertRedirects(response, "/login/?next=/manage/%3Fstatus%3Dlive", fetch_redirect_response=False)
        self.assertTrue(GuidePage.objects.get(pk=self.rules.pk).live)  # nothing happened

    def test_no_or_foreign_referer_falls_back_to_the_start_page(self):
        for referer in (None, "http://evil.example/x/", "http://testserver/login/"):
            client, response = self.logged_out_post(f"/read/{self.rules.pk}/", referer)
            self.assertRedirects(response, f"/login/?next=/read/{self.rules.pk}/", fetch_redirect_response=False)
            response = client.post(response["Location"], {"username": "pernik_manager", "password": PASSWORD}, follow=True)
            self.assertEqual(response.redirect_chain[-1], ("/", 302), referer)
            self.assertEqual(response.status_code, 200)

    def test_saving_the_editor_with_a_place_still_explains(self):
        client, response = self.logged_out_post(f"/manage/new/?place={self.marketing.pk}", f"http://testserver/manage/new/?place={self.marketing.pk}")
        self.assertContains(client.get(response["Location"]), "тя не е запазена")

    def test_a_button_address_opened_as_a_page(self):
        manager = self.client_for(self.pernik_manager)
        response = manager.get(f"/read/{self.rules.pk}/", follow=True)
        self.assertEqual(response.redirect_chain, [("/login/", 302), ("/", 302)])
        response = self.editor.get(f"/manage/{self.rules.pk}/delete/", follow=True)
        self.assertEqual(response.redirect_chain[-1], ("/manage/", 302))
        self.assertTrue(GuidePage.objects.filter(pk=self.rules.pk).exists())

    def csrf_client(self):
        client = Client(enforce_csrf_checks=True)
        client.get("/login/")
        return client, client.cookies["csrftoken"].value

    def test_second_login_tab(self):
        client, token = self.csrf_client()
        client.post("/login/", {"username": "pernik_staff", "password": PASSWORD, "csrfmiddlewaretoken": token})
        response = client.post("/login/", {"username": "pernik_staff", "password": PASSWORD, "csrfmiddlewaretoken": token}, follow=True)
        self.assertEqual(response.redirect_chain, [("/login/", 302), ("/", 302)])
        self.assertContains(response, "Изход (pernik_staff)")

    def test_old_login_page_while_logged_out(self):
        client, _ = self.csrf_client()
        response = client.post("/login/?next=/marketing/", {"username": "pernik_staff", "password": PASSWORD, "csrfmiddlewaretoken": "x" * 64}, follow=True)
        self.assertEqual(response.redirect_chain, [("/login/?next=/marketing/", 302)])
        self.assertContains(response, "Страницата за вход беше стара. Влезте отново.")
        self.assertNotContains(response, "Страницата е изтекла")

    def test_old_logout_button_after_a_login_in_another_tab(self):
        client, token = self.csrf_client()
        client.post("/login/", {"username": "pernik_staff", "password": PASSWORD, "csrfmiddlewaretoken": token})
        response = client.post("/manage/logout/", {"csrfmiddlewaretoken": token})  # the old page's token
        self.assertContains(response, "Не излязохте", status_code=403)
        self.assertContains(client.get("/"), "Изход (pernik_staff)")  # still in
        fresh = response.content.decode().split('name="csrfmiddlewaretoken" value="')[1].split('"')[0]
        response = client.post("/manage/logout/", {"csrfmiddlewaretoken": fresh})  # the page's own button
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        self.assertTrue(client.get("/")["Location"].startswith("/login/"))  # out now
        # already logged out (a second tab): just the login page
        response = client.post("/manage/logout/", {"csrfmiddlewaretoken": token})
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)

    def test_other_old_forms_keep_the_explanation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.pernik_manager)
        response = client.post(f"/read/{self.rules.pk}/", {"csrfmiddlewaretoken": "x" * 64})
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Страницата е изтекла", status_code=403)

    def test_pages_are_not_kept_by_the_browser(self):
        manager = self.client_for(self.pernik_manager)
        for client, url in ((manager, "/"), (manager, self.rules.url), (manager, "/search/?q=x"),
                            (self.editor, "/manage/"), (self.editor, f"/manage/{self.rules.pk}/reads/")):
            cache_control = client.get(url)["Cache-Control"]
            self.assertIn("no-store", cache_control, url)
            self.assertIn("private", cache_control, url)
        preview = self.editor.get(f"/manage/{self.rules.pk}/preview/")["Cache-Control"]
        self.assertIn("no-store", preview)  # a view that only said "private" (Wagtail's preview)
        for url in ("/manage/new/", f"/manage/new/?place={self.marketing.pk}", f"/manage/{self.rules.pk}/"):
            cache_control = self.editor.get(url)["Cache-Control"]
            self.assertIn("no-cache", cache_control, url)  # revalidated, but Back keeps the typed text
            self.assertIn("private", cache_control, url)
            self.assertNotIn("no-store", cache_control, url)
        self.assertNotIn("no-store", manager.get("/robots.txt").get("Cache-Control", ""))  # not a page

