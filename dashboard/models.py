from django.conf import settings
from django.db import models


class Account(models.Model):
    """Extra state of a /manage/ login."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="manage_account")
    must_change_password = models.BooleanField("Трябва да смени паролата", default=False)

    class Meta:
        verbose_name = "Акаунт за управление"


def must_change_password(user):
    return Account.objects.filter(user=user, must_change_password=True).exists()


def set_must_change_password(user, value):
    Account.objects.update_or_create(user=user, defaults={"must_change_password": value})
