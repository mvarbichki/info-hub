"""The /manage/ tabs: Потребители, Обекти (incl. the password sheet), Раздели, Категории, Статистика,
and a post's История / Последни промени."""

import json
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from wagtail.images.models import Image

from dashboard.access import departments_for, is_editor
from dashboard.models import must_change_password
from guides.models import CategoryPage, DepartmentPage, GuidePage
from venues.access import PASSWORD_ALPHABET, login_base, new_password, suggest_username
from venues.models import Venue, VenueAccount

from .base import PASSWORD, InfoHubTestCase, png

User = get_user_model()


class LoginNameTests(InfoHubTestCase):
    def test_login_names_follow_the_users_style(self):
        cases = {
            "Перник": "pernik", "София – Младост": "mladost", "София – Цариградско шосе": "carigradsko",
            "София – Орлов мост": "orlov", "София – Център": "centar", "Велико Търново": "vtarnovo",
            "Стара Загора": "szagora", "Пловдив – Център": "centar", "!!!": "obekt", "Ъ": "obekt", "Я": "ya",
        }
        for name, base in cases.items():
            self.assertEqual(login_base(name), base, name)

    def test_taken_names_get_a_number(self):
        self.assertEqual(suggest_username(self.pernik, "staff"), "pernik_staff2")
        self.assertEqual(suggest_username(self.pernik, "staff", taken={"pernik_staff", "pernik_staff2"}), "pernik_staff3")


class UsersTabTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.boss = self.client_for(self.admin)

    def new_account(self, venue, role, password, username=""):
        return self.boss.post("/manage/users/", {"role": role, "venue": venue.pk if venue else "", "username": username, "password": password, "department": ""})

    def test_one_list_with_every_kind(self):
        html = self.html(self.boss.get("/manage/users/"))
        for text in ('<td class="guide-table__title">pernik_staff</td>', '<td class="guide-table__title">marketing</td>',
                     "Служители на обект", "Управител на обект", "Редактор", "Администратор"):
            self.assertIn(text, html)

    def test_add_link_preselects_and_suggests(self):
        html = self.html(self.boss.get(f"/manage/users/?new_role=staff&new_venue={self.pernik.pk}"))
        self.assertIn(f'<option value="{self.pernik.pk}" selected>', html)
        self.assertIn('id="taken-usernames"', html)

    def test_venue_accounts(self):
        varna = Venue.objects.create(name="Варна")
        response = self.new_account(varna, "staff", "Rozova-Gradina-31")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="varna_staff", venue_account__venue=varna).exists())
        self.new_account(varna, "manager", "Zelena-Liva-52", " Varna_Shef ")
        account = User.objects.get(username="varna_shef")
        self.assertEqual(account.venue_account.role, "manager")
        self.assertTrue(account.groups.filter(name="Обекти – само преглед").exists())
        self.assertFalse(is_editor(account))
        self.new_account(self.pernik, "staff", "Kasa-Vtora-2026")
        self.assertTrue(User.objects.filter(username="pernik_staff2").exists())

    def test_refused_accounts_create_nothing(self):
        count = User.objects.count()
        cases = [
            (self.new_account(self.pernik, "staff", "Rozova-Gradina-31", "pernik_staff"), "Вече има такъв потребител"),
            (self.new_account(self.pernik, "staff", "Rozova-Gradina-31", "PERNIK_MANAGER"), "Вече има такъв потребител"),
            (self.new_account(self.pernik, "staff", "Rozova-Gradina-31", "перник"), "Само малки латински"),
            (self.new_account(self.pernik, "staff", "Rozova-Gradina-31", "a b"), "Само малки латински"),
            (self.new_account(self.pernik, "staff", "Rozova-Gradina-31", "x" * 41), ""),
            (self.new_account(self.pernik, "staff", "123"), "field-error"),
            (self.new_account(self.pernik, "staff", "pernik_staff2"), "field-error"),
            (self.new_account(self.pernik, "staff", ""), "Въведете парола"),
            (self.new_account(None, "staff", "Rozova-Gradina-31"), "Изберете обект"),
            (self.boss.post("/manage/users/", {"role": "staff", "venue": "99999", "password": "Rozova-Gradina-31"}), ""),
            (self.boss.post("/manage/users/", {"role": "admin", "venue": self.pernik.pk, "username": "hack", "password": "Rozova-Gradina-31"}), ""),
            (self.boss.post("/manage/users/", {"role": "editor", "username": "finance", "department": ""}), "Изберете раздел"),
            (self.boss.post("/manage/users/", {"role": "editor", "username": "", "department": self.marketing.pk}), "Въведете потребителско име"),
            (self.boss.post("/manage/users/", {"role": "editor", "username": "Pernik_Staff", "department": self.marketing.pk}), "Вече има"),
        ]
        for response, message in cases:
            self.assertEqual(response.status_code, 200)
            self.assertIn(message, self.html(response))
        self.assertEqual(User.objects.count(), count)

    def test_editors(self):
        response = self.boss.post("/manage/users/", {"role": "editor", "username": "Finance", "department": self.marketing.pk, "password": ""}, follow=True)
        finance = User.objects.get(username="finance")
        self.assertTrue(finance.check_password("finance"))
        self.assertTrue(must_change_password(finance))
        self.assertFalse(hasattr(finance, "venue_account"))
        self.assertContains(response, "Временна парола")
        self.boss.post(f"/manage/users/{finance.pk}/", {"username": "finance", "role": "editor", "department": self.cms.pk})
        self.assertEqual(list(departments_for(finance)), [self.cms])
        self.assertEqual(self.boss.get(f"/manage/users/{finance.pk}/password/").status_code, 404)
        finance.set_password("Something-Else-1")
        finance.save()
        self.boss.post(f"/manage/users/{finance.pk}/reset-password/")
        finance.refresh_from_db()
        self.assertTrue(finance.check_password("finance"))

    def test_kinds_cannot_be_switched(self):
        finance = User.objects.create_user("finance", password="x")
        from dashboard.access import set_department

        set_department(finance, self.marketing)
        self.boss.post(f"/manage/users/{finance.pk}/", {"username": "finance", "role": "staff", "venue": self.pernik.pk})
        self.assertFalse(hasattr(User.objects.get(pk=finance.pk), "venue_account"))
        self.boss.post(f"/manage/users/{self.pernik_staff.pk}/", {"username": "pernik_staff", "role": "editor", "department": self.marketing.pk})
        self.assertFalse(is_editor(User.objects.get(pk=self.pernik_staff.pk)))
        self.assertEqual(self.boss.post(f"/manage/users/{self.pernik_staff.pk}/reset-password/").status_code, 404)

    def test_edit_venue_account(self):
        url = f"/manage/users/{self.pernik_staff.pk}/"
        self.assertContains(self.boss.post(url, {"username": "pernik_manager", "role": "staff", "venue": self.pernik.pk}), "Вече има такъв потребител")
        self.assertContains(self.boss.post(url, {"username": "pernik_staff", "role": "staff", "venue": ""}), "Изберете обект")
        self.boss.post(url, {"username": "Pernik_Kasa", "role": "manager", "venue": self.sah.pk})
        account = User.objects.get(pk=self.pernik_staff.pk)
        self.assertEqual((account.username, account.venue_account.role, account.venue_account.venue), ("pernik_kasa", "manager", self.sah))
        html = self.html(self.boss.get(url))
        self.assertIn('name="venue"', html)
        self.assertNotIn('name="department"', html)

    def test_filters_and_search(self):
        html = self.html(self.boss.get("/manage/users/?role=manager"))
        self.assertIn("pernik_manager", html)
        self.assertNotIn(">pernik_staff<", html)
        html = self.html(self.boss.get(f"/manage/users/?venue={self.pernik.pk}"))
        self.assertIn(">pernik_staff<", html)
        self.assertNotIn(">mladost_staff<", html)
        html = self.html(self.boss.get("/manage/users/?q=МЛАДОСТ"))
        self.assertIn(">mladost_staff<", html)
        self.assertNotIn(">pernik_staff<", html)
        self.assertContains(self.boss.get("/manage/users/?q=zzz"), "Няма потребители по този филтър")
        self.assertEqual(self.boss.get("/manage/users/?venue=abc&role=xyz").status_code, 200)

    def test_actions_return_to_the_filtered_list_and_ignore_foreign_addresses(self):
        url = f"/manage/users/{self.pernik_manager.pk}/toggle/"
        self.assertEqual(self.boss.post(url, {"next": "/manage/users/?role=manager"})["Location"], "/manage/users/?role=manager")
        self.assertEqual(self.boss.post(url, {"next": "https://evil.example/"})["Location"], "/manage/users/")

    def test_no_actions_on_yourself_superusers_or_missing_users(self):
        for url in (f"/manage/users/{self.admin.pk}/", "/manage/users/99999/"):
            self.assertEqual(self.boss.get(url).status_code, 404)
        for action in ("toggle", "delete", "reset-password"):
            self.assertEqual(self.boss.post(f"/manage/users/{self.admin.pk}/{action}/").status_code, 404)

    def test_delete_account_ends_its_session(self):
        client = self.client_for(self.mladost_manager)
        self.boss.post(f"/manage/users/{self.mladost_manager.pk}/delete/")
        self.assertFalse(VenueAccount.objects.filter(user_id=self.mladost_manager.pk).exists())
        self.assertEqual(client.get("/").status_code, 302)

    def test_account_deleted_elsewhere_breaks_nothing(self):
        User.objects.get(username="manager").delete()
        self.assertEqual(self.boss.get("/manage/venues/").status_code, 200)
        self.assertEqual(self.boss.get("/manage/users/").status_code, 200)

    def test_only_the_superuser(self):
        editor = self.client_for(self.marketing_editor)
        for url in ("/manage/users/", "/manage/venues/", "/manage/departments/", f"/manage/users/{self.pernik_staff.pk}/"):
            self.assertEqual(editor.get(url).status_code, 403, url)
        self.assertEqual(editor.post("/manage/venues/passwords/").status_code, 403)

    def test_groups(self):
        self.assertTrue(Group.objects.filter(name="Маркетинг – редактори").exists())
        self.assertFalse(Group.objects.filter(name__in=["Moderators", "Editors"]).exists())


class VenuesTabTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.boss = self.client_for(self.admin)

    def test_create_rename_and_names_tidied(self):
        response = self.boss.post("/manage/venues/", {"name": "Пловдив-Камено"}, follow=True)
        self.assertContains(response, "Добавете му потребители")
        venue = Venue.objects.get(name="Пловдив – Камено")
        self.assertContains(self.boss.get("/manage/venues/"), "Няма потребители")
        self.assertContains(self.boss.post("/manage/venues/", {"name": "пловдив – камено"}), "Вече има обект")
        self.assertEqual(self.boss.post("/manage/venues/", {"name": " – "}).status_code, 200)
        self.boss.post(f"/manage/venues/{venue.pk}/", {"name": "Пловдив – Кючук"})
        venue.refresh_from_db()
        self.assertEqual(venue.name, "Пловдив – Кючук")
        self.assertContains(self.boss.post(f"/manage/venues/{venue.pk}/", {"name": "софия – младост"}), "Вече има обект")

    def test_renaming_keeps_the_accounts(self):
        self.boss.post(f"/manage/venues/{self.pernik.pk}/", {"name": "Перник – Център"})
        self.assertEqual(self.pernik.accounts.count(), 2)

    def test_delete_asks_and_removes_accounts(self):
        self.assertContains(self.boss.get("/manage/venues/"), "и потребителите му (2)")
        self.boss.post(f"/manage/venues/{self.sah.pk}/delete/")
        self.assertFalse(Venue.objects.filter(pk=self.sah.pk).exists())
        self.assertFalse(User.objects.filter(username__startswith="mladost_").exists())

    def test_training_venue_stays(self):
        response = self.boss.post(f"/manage/venues/{self.training.pk}/delete/", follow=True)
        self.assertContains(response, "не може да се изтрие")
        self.assertTrue(Venue.objects.filter(pk=self.training.pk).exists())

    def test_missing_venue(self):
        self.assertEqual(self.boss.get("/manage/venues/99999/").status_code, 404)
        self.assertEqual(self.boss.post("/manage/venues/99999/delete/").status_code, 404)


class PasswordSheetTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.boss = self.client_for(self.admin)

    def sheet(self, response):
        return dict(re.findall(r'<td class="code">([a-z_0-9]+)</td>\s*<td class="code">([a-z0-9-]+)</td>', self.html(response)))

    def test_generated_passwords(self):
        pattern = re.compile(rf"[{PASSWORD_ALPHABET}]{{4}}-[{PASSWORD_ALPHABET}]{{4}}-[{PASSWORD_ALPHABET}]{{4}}")
        passwords = {new_password() for _ in range(50)}
        self.assertEqual(len(passwords), 50)
        for password in passwords:
            self.assertRegex(password, pattern)
            self.assertTrue(any(c.isdigit() for c in password))

    def test_one_venue(self):
        pc = Client()
        pc.post("/login/", {"username": "pernik_staff", "password": PASSWORD})
        response = self.boss.post(f"/manage/venues/{self.pernik.pk}/passwords/")
        found = self.sheet(response)
        self.assertEqual(set(found), {"pernik_staff", "pernik_manager"})
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, "http://testserver/login/")
        self.assertContains(response, "няма да се покажат отново")
        user = User.objects.get(username="pernik_staff")
        self.assertTrue(user.check_password(found["pernik_staff"]))
        self.assertFalse(user.check_password(PASSWORD))
        self.assertEqual(pc.get("/").status_code, 302)  # the venue's PC is logged out
        self.assertEqual(Client().post("/login/", {"username": "pernik_staff", "password": found["pernik_staff"]}).status_code, 302)
        self.assertTrue(User.objects.get(username="mladost_staff").check_password(PASSWORD))

    def test_all_working_venues_without_training_and_stopped(self):
        Venue.objects.filter(pk=self.sah.pk).update(is_active=False)
        response = self.boss.post("/manage/venues/passwords/")
        self.assertEqual(set(self.sheet(response)), {"pernik_staff", "pernik_manager"})
        self.assertTrue(User.objects.get(pk=self.training_staff.pk).check_password(PASSWORD))
        self.assertTrue(User.objects.get(username="mladost_staff").check_password(PASSWORD))

    def test_a_page_per_venue(self):
        response = self.boss.post("/manage/venues/passwords/")
        self.assertEqual(self.html(response).count('<section class="sheet">'), 2)

    def test_nothing_to_renew(self):
        empty = Venue.objects.create(name="Празен")
        self.assertContains(self.boss.post(f"/manage/venues/{empty.pk}/passwords/", follow=True), "Няма потребители")
        self.assertEqual(self.boss.get("/manage/venues/passwords/").status_code, 405)


class DepartmentsTabTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.boss = self.client_for(self.admin)

    def create(self, **changes):
        data = {"title": "Финанси", "slug": "finance", "description": "", "color": "blue", "icon": "info", **changes}
        return self.boss.post("/manage/departments/", data)

    def test_create_with_group_and_folder(self):
        self.assertEqual(self.create().status_code, 302)
        finance = DepartmentPage.objects.get(slug="finance")
        self.assertTrue(finance.live)
        self.assertTrue(Group.objects.filter(name="Финанси – редактори").exists())
        self.assertEqual(self.client_for(self.pernik_staff).get("/finance/").status_code, 200)

    def test_refused(self):
        self.create()
        for changes, message in (({"title": "финанси", "slug": "other"}, "Вече има раздел с това име"),
                                 ({"title": "Друг", "slug": "finance"}, "Вече има раздел с този адрес"),
                                 ({"title": "Вход", "slug": "login"}, "се използва от сайта"),
                                 ({"title": "Четене", "slug": "read"}, "се използва от сайта"),
                                 ({"title": "Лош", "slug": "Лош адрес"}, "Само малки латински")):
            self.assertContains(self.create(**changes), message)

    def test_rename_keeps_address_folder_and_group(self):
        self.create()
        finance = DepartmentPage.objects.get(slug="finance")
        self.boss.post(f"/manage/departments/{finance.pk}/", {"title": "Счетоводство", "description": "", "color": "green", "icon": "book"})
        finance.refresh_from_db()
        self.assertEqual((finance.title, finance.slug, finance.color), ("Счетоводство", "finance", "green"))
        self.assertTrue(Group.objects.filter(name="Счетоводство – редактори").exists())

    def test_delete_only_when_empty(self):
        response = self.boss.post(f"/manage/departments/{self.marketing.pk}/delete/", follow=True)
        self.assertContains(response, "се управлява от: marketing")
        self.create()
        finance = DepartmentPage.objects.get(slug="finance")
        self.save_post(self.boss, title="Отчет", place=finance.pk)
        self.assertContains(self.boss.post(f"/manage/departments/{finance.pk}/delete/", follow=True), "Изтрийте ги първо")
        GuidePage.objects.child_of(finance).delete()
        self.boss.post(f"/manage/departments/{finance.pk}/delete/")
        self.assertFalse(DepartmentPage.objects.filter(slug="finance").exists())
        self.assertFalse(Group.objects.filter(name="Финанси – редактори").exists())

    def test_order_up_and_down(self):
        def order():
            return [d.slug for d in DepartmentPage.objects.order_by("path")]

        def move(department, direction):
            return self.boss.post(f"/manage/departments/{department.pk}/move/", {"direction": direction})

        self.assertEqual(order(), ["it", "cms", "marketing", "hr"])  # setup_infohub's order
        self.assertEqual(move(self.marketing, "up").status_code, 302)
        self.assertEqual(order(), ["it", "marketing", "cms", "hr"])
        move(self.it, "down")
        self.assertEqual(order(), ["marketing", "it", "cms", "hr"])
        move(self.marketing, "up")  # already first
        move(DepartmentPage.objects.get(slug="hr"), "down")  # already last
        move(self.it, "sideways")
        self.assertEqual(order(), ["marketing", "it", "cms", "hr"])
        self.assertEqual(self.boss.get(f"/manage/departments/{self.it.pk}/move/").status_code, 405)
        self.assertEqual(self.client_for(self.marketing_editor).post(f"/manage/departments/{self.it.pk}/move/", {"direction": "up"}).status_code, 403)
        # The site menu and the home page follow, the addresses stay.
        home = self.html(self.client_for(self.pernik_staff).get("/"))
        self.assertLess(home.index("/marketing/"), home.index("/it/"))
        self.assertLess(home.index("/it/"), home.index("/hr/"))
        self.assertEqual(self.client_for(self.pernik_staff).get("/it/").status_code, 200)

    def test_drafts_are_counted(self):
        self.save_post(self.boss, title="Чернова", action="draft")
        self.assertContains(self.boss.get("/manage/departments/"), "1 чернови")


class CategoriesTabTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)

    def test_create_rename_delete(self):
        self.editor.post("/manage/categories/", {"title": "  Промоции  ", "department": self.marketing.pk})
        category = CategoryPage.objects.get(title="Промоции")
        self.assertTrue(category.live)
        self.assertContains(self.editor.post("/manage/categories/", {"title": "ПРОМОЦИИ", "department": self.marketing.pk}), "Вече има категория")
        self.editor.post("/manage/categories/", {"title": "Игри", "department": self.marketing.pk})
        response = self.editor.post(f"/manage/categories/{category.pk}/rename/", {"title": "игри"}, follow=True)
        self.assertContains(response, "Вече има категория")
        self.editor.post(f"/manage/categories/{category.pk}/rename/", {"title": "Акции"})
        category.refresh_from_db()
        self.assertEqual((category.title, category.slug), ("Акции", "promotsii"))
        _, post = self.save_post(self.editor, title="В категория", place=category.pk)
        self.assertEqual(post.get_parent().pk, category.pk)
        self.assertContains(self.editor.post(f"/manage/categories/{category.pk}/delete/", follow=True), "има 1 публикации")
        post.delete()
        self.editor.post(f"/manage/categories/{category.pk}/delete/")
        self.assertFalse(CategoryPage.objects.filter(pk=category.pk).exists())

    def test_other_departments_categories_are_out_of_reach(self):
        self.client_for(self.admin).post("/manage/categories/", {"title": "Системни", "department": self.cms.pk})
        category = CategoryPage.objects.get(title="Системни")
        self.assertEqual(self.editor.post(f"/manage/categories/{category.pk}/delete/").status_code, 404)
        self.assertEqual(self.editor.post("/manage/categories/", {"title": "Чужда", "department": self.cms.pk}).status_code, 200)
        self.assertFalse(CategoryPage.objects.filter(title="Чужда").exists())


class StatsTabTests(InfoHubTestCase):
    def test_per_venue_and_filters(self):
        editor = self.client_for(self.marketing_editor)
        _, guide = self.save_post(editor, title="Принтер")
        staff = self.client_for(self.pernik_staff)
        staff.get(guide.url)
        staff.get("/search/?q=липсващо")
        boss = self.client_for(self.admin)
        html = self.html(boss.get("/manage/stats/"))
        self.assertIn("По обекти", html)
        self.assertIn("Перник", html)
        self.assertNotIn("Обучение</a>", html)
        self.assertContains(boss.get(f"/manage/stats/?venue={self.pernik.pk}"), "липсващо")
        for query in ("?days=7", "?days=999", "?venue=abc", "?department=abc", "?page=99"):
            self.assertEqual(editor.get("/manage/stats/" + query).status_code, 200, query)


class PanelExtrasTests(InfoHubTestCase):
    def test_list_filters_and_storage(self):
        boss = self.client_for(self.admin)
        self.save_post(boss, title="В маркетинг", place=self.marketing.pk)
        self.save_post(boss, title="В ИТ", place=self.it.pk)
        table = self.html(boss.get(f"/manage/?department={self.it.pk}&q=ит")).split('<table class="guide-table">')[1]
        self.assertIn("В ИТ", table)  # the title search ignores the case of Cyrillic letters too
        self.assertNotIn("В маркетинг", table)
        self.assertIn("Място на сървъра", self.html(boss.get("/manage/")))
        self.assertNotIn("Място на сървъра", self.html(self.client_for(self.marketing_editor).get("/manage/")))

    def test_hidden_category_can_be_shown(self):
        category = CategoryPage(title="Скрита", slug="skrita", live=False)
        self.marketing.add_child(instance=category)
        editor = self.client_for(self.marketing_editor)
        editor.post(f"/manage/categories/{category.pk}/publish/")
        category.refresh_from_db()
        self.assertTrue(category.live)

    def test_training_accounts_avoid_taken_names(self):
        from venues.access import training_venue

        Venue.objects.filter(is_training=True).delete()
        User.objects.filter(username="manager").delete()
        venue, created = training_venue()
        self.assertTrue(created)
        self.assertEqual(sorted(a.user.username for a in venue.accounts.select_related("user")), ["manager", "training_staff"])

    def test_admin_user_forms_need_no_name_or_email(self):
        boss = self.client_for(self.admin)
        response = boss.post("/admin/users/new/", {
            "username": "itnew", "email": "", "first_name": "", "last_name": "",
            "password1": "Some-Strong-Pass-26", "password2": "Some-Strong-Pass-26", "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="itnew").exists())
        self.assertEqual(boss.get("/admin/").status_code, 200)

    def test_add_department_command_refuses_reserved_addresses(self):
        from django.core.management import CommandError, call_command

        with self.assertRaises(CommandError):
            call_command("add_department", "Вход", "login")


class HistoryTests(InfoHubTestCase):
    """История of a post: its versions, who did what, bringing an older version back; Последни промени."""

    def setUp(self):
        super().setUp()
        self.editor = self.client_for(self.marketing_editor)
        self.picture = self.upload(self.editor, png(), "image")[1]["item"]
        _, self.guide = self.save_post(self.editor, title="Томбола", summary="Първа версия",
                                       body=json.dumps([{"type": "image", "image": self.picture}]))
        self.first = self.guide.latest_revision_id
        self.save_post(self.editor, url=f"/manage/{self.guide.pk}/", title="Томбола", summary="Втора версия",
                       body=json.dumps([{"type": "text", "html": "<p>без снимка</p>"}]))
        self.guide.refresh_from_db()

    def test_history_lists_versions_and_who(self):
        html = self.html(self.editor.get(f"/manage/{self.guide.pk}/history/"))
        self.assertIn("История: Томбола", html)
        self.assertEqual(html.count("<td>marketing</td>"), 4)  # saved + published, twice
        self.assertIn("<td>Публикувана</td>", html)
        self.assertIn("На сайта сега", html)
        self.assertIn(f"?revision={self.first}\">Зареди в редактора", html)
        self.assertNotIn(f"?revision={self.guide.latest_revision_id}\">Зареди", html)  # the current one
        self.assertEqual(self.client_for(self.cms_editor).get(f"/manage/{self.guide.pk}/history/").status_code, 404)
        response = self.client_for(self.pernik_staff).get(f"/manage/{self.guide.pk}/history/")
        self.assertEqual((response.status_code, response["Location"].split("?")[0]), (302, "/login/"))

    def test_an_older_version_comes_back_with_its_picture(self):
        response = self.editor.get(f"/manage/{self.guide.pk}/?revision={self.first}")
        html = self.html(response)
        self.assertIn("Заредена е по-старата версия", html)
        self.assertIn(">Първа версия</textarea>", html)
        blocks = self.editor_config(response)["blocks"]
        self.assertEqual(blocks[0]["image"]["id"], self.picture["id"])
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.summary, "Втора версия")  # nothing changed by just looking
        self.save_post(self.editor, url=f"/manage/{self.guide.pk}/?revision={self.first}", title="Томбола",
                       summary="Първа версия", body=json.dumps(blocks))
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.summary, "Първа версия")
        self.assertEqual(self.guide.body[0].block_type, "image")
        page = self.html(self.client_for(self.pernik_staff).get(self.guide.url))
        self.assertIn(Image.objects.get(pk=self.picture["id"]).title, page)

    def test_preview_of_an_older_version(self):
        html = self.html(self.editor.get(f"/manage/{self.guide.pk}/preview/?revision={self.first}"))
        self.assertIn("Първа версия", html)
        self.assertIn("Втора версия", self.html(self.editor.get(f"/manage/{self.guide.pk}/preview/")))

    def test_bad_revision_ids(self):
        _, other = self.save_post(self.editor, title="Друга")
        for wanted in ("abc", "999999", str(other.latest_revision_id)):
            self.assertEqual(self.editor.get(f"/manage/{self.guide.pk}/?revision={wanted}").status_code, 404, wanted)
            self.assertEqual(self.editor.get(f"/manage/{self.guide.pk}/preview/?revision={wanted}").status_code, 404, wanted)

    def test_a_missing_picture_is_reported(self):
        Image.objects.filter(pk=self.picture["id"]).delete()
        html = self.html(self.editor.get(f"/manage/{self.guide.pk}/?revision={self.first}"))
        self.assertIn("1 снимки или файла от тази версия вече ги няма", html)

    def test_recent_changes_with_deletes(self):
        boss = self.client_for(self.admin)
        _, gone = self.save_post(self.editor, title="За изтриване")
        self.editor.post(f"/manage/{gone.pk}/toggle/")
        self.editor.post(f"/manage/{gone.pk}/delete/")
        html = self.html(boss.get("/manage/activity/"))
        self.assertIn("<td>Изтрита</td>", html)
        self.assertIn("<td>Архивирана</td>", html)
        self.assertIn("За изтриване", html)
        self.assertIn(f'href="/manage/{self.guide.pk}/history/">Томбола', html)
        own = self.html(self.editor.get("/manage/activity/"))
        self.assertIn("Томбола", own)
        self.assertNotIn("За изтриване", own)  # deleted posts: only the superuser
        self.assertNotIn("Томбола", self.html(self.client_for(self.cms_editor).get("/manage/activity/")))
