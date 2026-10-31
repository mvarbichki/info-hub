"""A read-only health check of the site's database and files, for any server (SQLite, PostgreSQL,
MariaDB). Everything runs in a transaction that is rolled back, so nothing is changed."""

from collections import Counter

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from wagtail.documents.models import Document
from wagtail.images.models import Image
from wagtail.models import Collection, Page, Site

from dashboard.access import departments_for, editor_groups, is_editor
from dashboard.models import Account
from guides.audience import AUDIENCE_ALL, AUDIENCE_MANAGERS, visible_guides, visible_media
from guides.departments import RESERVED_SLUGS, department_group
from guides.editor import media_ids, to_editor
from guides.models import CategoryPage, DepartmentMedia, DepartmentPage, DocumentPreview, GuidePage
from guides.previews import CONVERTIBLE
from home.models import HomePage, SiteBranding
from stats.models import Ack, Seen, Vote
from venues.access import VENUE_GROUP, reader
from venues.models import MANAGER, Venue, VenueAccount


class Rollback(Exception):
    pass


def should_see(guide, account, venue_ids):
    """Who may see a post, written out separately from guides/audience.py (which is checked against it)."""
    if not guide.live:
        return False
    if guide.audience == AUDIENCE_ALL:
        return True
    if account.venue_id not in venue_ids:
        return False
    return guide.audience != AUDIENCE_MANAGERS or account.role == MANAGER


class Command(BaseCommand):
    help = (
        "Проверка на базата и файловете, без да променя нищо: страници, раздели, публикации, снимки и файлове "
        "на диска, PDF копия, потребители и обекти, кой какво вижда. Показва проблемите; без проблеми завършва с OK."
    )

    def handle(self, *args, **options):
        self.problems, self.notes = [], []
        try:
            with transaction.atomic():
                self.database()
                self.structure()
                self.posts()
                self.files()
                self.accounts()
                self.visibility()
                raise Rollback
        except Rollback:
            pass
        for note in self.notes:
            self.stdout.write(f"  - {note}")
        for problem in self.problems:
            self.stdout.write(self.style.ERROR(f"  ! {problem}"))
        if self.problems:
            raise CommandError(f"Проблеми: {len(self.problems)}")
        self.stdout.write(self.style.SUCCESS("OK: няма проблеми."))

    def bad(self, message):
        self.problems.append(message)

    def database(self):
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA integrity_check")
                if cursor.fetchall() != [("ok",)]:
                    self.bad("SQLite: файлът на базата е повреден (integrity_check)")
                cursor.execute("PRAGMA foreign_key_check")
                if cursor.fetchall():
                    self.bad("SQLite: записи сочат към изтрити редове (foreign_key_check)")
        self.notes.append(f"база: {connection.vendor}")

    def structure(self):
        for model in (Page, Collection):
            if any(model.find_problems()):
                self.bad(f"дървото {model.__name__} има грешки: {model.find_problems()}")
        sites = list(Site.objects.all())
        homes = list(HomePage.objects.all())
        if len(sites) != 1 or len(homes) != 1 or sites[0].root_page_id != homes[0].pk:
            self.bad(f"сайтове {len(sites)}, начални страници {len(homes)}: трябва по една, свързани")
            return
        home = homes[0]
        for page in Page.objects.child_of(home).specific():
            if not isinstance(page, DepartmentPage):
                self.bad(f"„{page.title}“ под началната страница не е раздел")
        for department in DepartmentPage.objects.order_by("path"):
            group = department_group(department)
            if department.slug in RESERVED_SLUGS:
                self.bad(f"раздел „{department.title}“: адресът /{department.slug}/ е запазен")
            if group is None:
                self.bad(f"раздел „{department.title}“ няма група редактори")
            elif group.permissions.filter(codename="access_admin").exists():
                self.bad(f"групата „{group.name}“ има достъп до /admin/")
            if not DepartmentMedia.objects.filter(department=department).exists():
                self.bad(f"раздел „{department.title}“ няма папка за файлове")
        for category in CategoryPage.objects.all():
            if not isinstance(category.get_parent().specific, DepartmentPage):
                self.bad(f"категория „{category.title}“ не е в раздел")
        branding = SiteBranding.for_site(sites[0])
        if branding.logo and not branding.logo.file.storage.exists(branding.logo.file.name):
            self.bad("файлът на логото липсва")

    def posts(self):
        images = set(Image.objects.values_list("pk", flat=True))
        documents = set(Document.objects.values_list("pk", flat=True))
        folders = dict(DepartmentMedia.objects.values_list("department_id", "collection_id"))
        status = Counter()
        for guide in GuidePage.objects.all():
            department = guide.department
            if department is None:
                self.bad(f"публикация #{guide.pk} „{guide.title}“ не е в раздел")
                continue
            status["чернова" if guide.is_draft else "на сайта" if guide.live else "архивирана"] += 1
            for version, label in ((guide, "на сайта"), (guide.get_latest_revision_as_object(), "последна версия")):
                name = f"#{guide.pk} „{guide.title}“ ({label})"
                used_images, used_documents = media_ids(to_editor(version.body))
                if set(used_images) - images or set(used_documents) - documents:
                    self.bad(f"{name}: липсват снимки/файлове")
                for model, ids in ((Image, used_images), (Document, used_documents)):
                    if model.objects.filter(pk__in=ids).exclude(collection_id=folders.get(department.pk)).exists():
                        self.bad(f"{name}: снимка/файл не е в папката на раздела")
                stored = version.uploaded_media or {}
                if set(used_images) - set(stored.get("images", [])) or set(used_documents) - set(stored.get("documents", [])):
                    self.bad(f"{name}: списъкът uploaded_media не съдържа всички ползвани файлове")
                venues = [v.pk for v in version.venues.all()]
                if version.audience == AUDIENCE_ALL and venues:
                    self.bad(f"{name}: „Всички обекти“, но със списък обекти")
            if guide.live:
                parts = [guide.title, guide.summary, *guide.body.stream_block.get_searchable_content(guide.body)]
                if guide.search_text != " ".join(p for p in parts if p).lower():
                    self.bad(f"#{guide.pk} „{guide.title}“: текстът за търсене е остарял")
        self.notes.append(f"публикации: {dict(status) or 0}")

    def files(self):
        missing = 0
        for model in (Image, Document, DocumentPreview):
            for obj in model.objects.all():
                if not obj.file or not obj.file.storage.exists(obj.file.name):
                    missing += 1
                    self.bad(f"{model.__name__} #{obj.pk}: файлът липсва на диска ({obj.file.name})")
        without = [d.title for d in Document.objects.filter(preview__isnull=True) if d.file_extension.lower() in CONVERTIBLE]
        self.notes.append(
            f"снимки {Image.objects.count()}, файлове {Document.objects.count()}, PDF копия {DocumentPreview.objects.count()}"
            + (f"; без PDF копие: {', '.join(without)} (manage.py make_previews)" if without else "")
        )

    def accounts(self):
        venue_group = Group.objects.filter(name=VENUE_GROUP).first()
        if venue_group is None:
            self.bad(f"групата „{VENUE_GROUP}“ липсва")
        elif venue_group.permissions.exists():
            self.bad(f"групата „{VENUE_GROUP}“ има права: всеки обект би ги получил")
        editor_ids = set(editor_groups().values_list("pk", flat=True))
        kinds = Counter()
        for user in User.objects.all():
            account = VenueAccount.objects.filter(user=user).first()
            groups = set(user.groups.values_list("pk", flat=True))
            if account:
                kinds["обекти"] += 1
                if user.is_superuser or user.is_staff or groups & editor_ids or user.user_permissions.exists():
                    self.bad(f"{user.username}: акаунт на обект с права на редактор/администратор")
                if venue_group and venue_group.pk not in groups:
                    self.bad(f"{user.username}: не е в групата „{VENUE_GROUP}“")
                if reader(user) is None:
                    self.bad(f"{user.username}: акаунтът на обекта не се разпознава")
            elif user.is_superuser:
                kinds["администратори"] += 1
            elif is_editor(user):
                kinds["редактори"] += 1
                if venue_group and venue_group.pk in groups:
                    self.bad(f"{user.username}: редактор в групата на обектите")
                if not departments_for(user).exists():
                    self.bad(f"{user.username}: редактор без раздел")
            else:
                self.bad(f"{user.username}: нито обект, нито редактор, нито администратор")
        if Account.objects.filter(user__venue_account__isnull=False, must_change_password=True).exists():
            self.bad("акаунт на обект трябва да смени паролата си (а не може)")
        names = Counter(name.casefold() for name in Venue.objects.values_list("name", flat=True))
        for name, count in names.items():
            if count > 1:
                self.bad(f"обектът „{name}“ е записан {count} пъти")
        if Venue.objects.filter(is_training=True).count() != 1:
            self.bad("трябва да има точно един обект за обучение")
        for model in (Seen, Ack, Vote):
            if model.objects.filter(user__venue_account__isnull=True).exists():
                self.bad(f"{model.__name__}: записи от потребител, който не е обект")
        if Vote.objects.filter(helpful=True).exclude(reason="").exists():
            self.bad("отговор „Да“ с причина")
        working = Venue.objects.filter(is_training=False, is_active=True).count()
        self.notes.append(f"потребители: {dict(kinds)}; обекти {Venue.objects.count()} ({working} работят)")

    def visibility(self):
        """Every venue account against every post, and the files that come with them."""
        guides = list(GuidePage.objects.all())
        venues = {g.pk: set(g.venues.values_list("pk", flat=True)) for g in guides}
        checks = 0
        for account in VenueAccount.objects.select_related("user"):
            visible = set(visible_guides(account.user).values_list("pk", flat=True))
            expected = {g.pk for g in guides if should_see(g, account, venues[g.pk])}
            checks += len(guides)
            for pk in visible - expected:
                self.bad(f"{account.user.username} вижда публикация #{pk}, която не е за него")
            for pk in expected - visible:
                self.bad(f"{account.user.username} не вижда публикация #{pk}, която е за него")
            images, documents = visible_media(account.user)
            for guide in guides:
                media = guide.uploaded_media or {}
                own_images, own_documents = set(media.get("images", [])), set(media.get("documents", []))
                if guide.pk in expected and not (own_images <= images and own_documents <= documents):
                    self.bad(f"{account.user.username}: не може да отвори файловете на #{guide.pk}")
            allowed_images, allowed_documents = set(), set()
            for guide in guides:
                if guide.pk in expected:
                    allowed_images.update((guide.uploaded_media or {}).get("images", []))
                    allowed_documents.update((guide.uploaded_media or {}).get("documents", []))
            if images - allowed_images or documents - allowed_documents:
                self.bad(f"{account.user.username}: може да отвори файлове на публикации, които не са за него")
        self.notes.append(f"кой какво вижда: {checks} проверки (акаунт × публикация)")
