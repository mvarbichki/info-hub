from django.contrib.auth.backends import ModelBackend


class VenueBackend(ModelBackend):
    """Django's login, except that the accounts of a stopped venue can't log in.

    Django also checks this on every request of a logged-in user, so a stopped venue's PCs can't
    use the site at once. Their sessions are kept: when the venue is started again, they continue
    without a new login.
    """

    def user_can_authenticate(self, user):
        if not super().user_can_authenticate(user):
            return False
        from .models import VenueAccount

        return not VenueAccount.objects.filter(user=user, venue__is_active=False).exists()
