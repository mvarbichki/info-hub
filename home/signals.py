from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from wagtail.users.models import UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def default_admin_language(sender, instance, created, raw=False, **kwargs):
    """New users get the English Wagtail admin (its Bulgarian translation is incomplete).
    Not for users loaded from a file (import_site): their profile comes with them."""
    if created and not raw:
        UserProfile.objects.get_or_create(user=instance, defaults={"preferred_language": "en"})
