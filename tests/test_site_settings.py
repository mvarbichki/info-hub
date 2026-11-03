"""Настройки (superuser): the site's name, logo and footer, in /manage/ instead of Wagtail's /admin/."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from wagtail.images.models import Image
from wagtail.models import Site

from home.models import SiteBranding

from .base import InfoHubTestCase, png


def branding():
    return SiteBranding.for_site(Site.objects.get(is_default_site=True))


class SiteSettingsTests(InfoHubTestCase):
    def setUp(self):
        super().setUp()
        self.boss = self.client_for(self.admin)

    def test_only_the_superuser(self):
        self.assertEqual(self.client_for(self.marketing_editor).get("/manage/settings/").status_code, 403)
        self.assertTrue(self.client_for(self.pernik_staff).get("/manage/settings/")["Location"].startswith("/login/"))
        self.assertNotContains(self.client_for(self.marketing_editor).get("/manage/"), "/manage/settings/")
        self.assertContains(self.boss.get("/manage/"), 'href="/manage/settings/"')

    def test_name_footer_and_logo(self):
        response = self.boss.post("/manage/settings/", {
            "site_name": "Помощ за залите", "footer_text": "ИТ: вътр. 123", "logo": png(400, 120, name="logo.png"),
        }, follow=True)
        self.assertContains(response, "Настройките са запазени")
        current = branding()
        self.assertEqual((current.site_name, current.footer_text), ("Помощ за залите", "ИТ: вътр. 123"))
        logo = current.logo
        self.assertEqual((logo.width, logo.height), (400, 120))
        login = Client().get("/login/")
        self.assertContains(login, "Помощ за залите")
        self.assertEqual(Client().get(logo.get_rendition("height-112").url).status_code, 200)  # the logo is public
        home = self.html(self.client_for(self.pernik_staff).get("/"))
        self.assertIn("ИТ: вътр. 123", home)

        # a new logo replaces the old one, which is deleted
        self.boss.post("/manage/settings/", {"site_name": "Помощ за залите", "logo": png(300, 100, color="blue", name="new.png")})
        self.assertFalse(Image.objects.filter(pk=logo.pk).exists())
        self.assertEqual(branding().logo.width, 300)
        # name and footer only: the logo stays
        self.boss.post("/manage/settings/", {"site_name": "Информационен център", "footer_text": ""})
        self.assertEqual(branding().logo.width, 300)
        self.assertEqual(branding().footer_text, "")
        # „Без лого“
        old = branding().logo
        self.boss.post("/manage/settings/", {"site_name": "Информационен център", "remove_logo": "on"})
        self.assertIsNone(branding().logo)
        self.assertFalse(Image.objects.filter(pk=old.pk).exists())

    def test_wrong_input(self):
        response = self.boss.post("/manage/settings/", {"site_name": "", "logo": SimpleUploadedFile("x.png", b"not a picture")})
        self.assertContains(response, "field-error")
        self.assertContains(response, "Име на сайта")
        self.assertEqual(Image.objects.count(), 0)
        with override_settings(INFOHUB_LIMITS_MB={"image": 0, "video": 300, "file": 50}):
            response = self.boss.post("/manage/settings/", {"site_name": "Х", "logo": png()})
        self.assertContains(response, "по-голям от 0 MB")
        self.assertEqual(branding().site_name, "Информационен център")
