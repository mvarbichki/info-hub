from django.conf import settings
from django.db import models

STAFF, MANAGER = "staff", "manager"
ROLE_CHOICES = [(STAFF, "Служители на обект"), (MANAGER, "Управител на обект")]


class Venue(models.Model):
    """A venue (обект). Its read-only logins are VenueAccounts, made in /manage/ → Потребители.

    A stopped venue (is_active False) keeps its accounts, but none of them can log in
    (venues.backends). The training venue („Обучение“) is a normal venue that the statistics leave out.
    """

    name = models.CharField("Име", max_length=100, unique=True)
    is_active = models.BooleanField("Работи", default=True)
    is_training = models.BooleanField("Обучение", default=False, help_text="Не се брои в статистиката.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Обект"
        verbose_name_plural = "Обекти"

    def __str__(self):
        return self.name


class VenueAccount(models.Model):
    """A login of a venue: its staff (служители) or its venue manager (управител).

    A venue may have several accounts per role (e.g. one per PC). The venue manager sees everything
    for the venue's staff plus posts only for venue managers. No venue account can open /manage/.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="venue_account")
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="accounts")
    role = models.CharField("Роля", max_length=10, choices=ROLE_CHOICES)

    class Meta:
        ordering = ["venue__name", "-role", "user__username"]  # staff before the manager
        verbose_name = "Потребител на обект"
        verbose_name_plural = "Потребители на обекти"

    def __str__(self):
        return f"{self.user.username} ({self.venue}, {self.get_role_display()})"
