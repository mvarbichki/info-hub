from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from dashboard.access import create_editor
from guides.departments import create_department
from guides.models import DepartmentPage
from home.models import HomePage
from venues.access import training_venue

# In menu order (what venue staff need most first). Short names for staff; the addresses stay.
DEFAULT_DEPARTMENTS = [
    ("Технически", "it", "Технически ръководства и решения на често срещани проблеми.", "purple", "computer"),
    ("Казино система", "cms", "Ръководства и информация за казино мениджмънт системата.", "teal", "tools"),
    ("Маркетинг", "marketing", "Текущи кампании, промоции и материали.", "orange", "megaphone"),
    ("Персонал", "hr", "Информация за служители, документи и процедури.", "green", "people"),
]

# Editors per department. The first password is the username and must be changed at first login.
DEFAULT_USERS = [("marketing", "marketing"), ("cms", "cms")]


class Command(BaseCommand):
    help = "Първоначална настройка: начална страница, разделите, потребителите им и обекта за обучение. Може да се пуска многократно."

    def handle(self, *args, **options):
        home = HomePage.objects.first()
        if home.title == "Home":
            home.title = "Начало"
            home.draft_title = "Начало"
            home.intro = "Ръководства, новини и кампании за всички обекти – на едно място."
            home.save()
            home.save_revision().publish()

        for title, slug, description, color, icon in DEFAULT_DEPARTMENTS:
            department, group, created = create_department(title, slug, description, color, icon)
            state = "Създаден" if created else "Вече съществува"
            self.stdout.write(f"{state}: {department.title} – група „{group.name}“")

        for username, department_slug in DEFAULT_USERS:
            if get_user_model().objects.filter(username=username).exists():
                self.stdout.write(f"Вече съществува: потребител „{username}“")
                continue
            create_editor(username, DepartmentPage.objects.get(slug=department_slug))
            self.stdout.write(f"Създаден: потребител „{username}“ (временна парола „{username}“)")

        venue, created = training_venue()
        state = "Създаден" if created else "Вече съществува"
        logins = ", ".join(a.user.username for a in venue.accounts.select_related("user"))
        self.stdout.write(f"{state}: обект „{venue.name}“ ({logins}). Паролите се задават в /manage/ → Потребители.")

        self.stdout.write(self.style.SUCCESS("Готово."))
