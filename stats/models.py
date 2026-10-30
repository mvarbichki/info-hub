from django.conf import settings
from django.db import models


class GuideStat(models.Model):
    """Daily counters for one guide per venue (venue accounts only, not the training venue). No person is stored."""

    guide = models.ForeignKey("guides.GuidePage", on_delete=models.CASCADE, related_name="stats")
    # Empty for counts from before the venue accounts (the shared login) or of a deleted venue.
    venue = models.ForeignKey("venues.Venue", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    day = models.DateField(db_index=True)
    views = models.PositiveIntegerField(default=0)
    helpful = models.PositiveIntegerField(default=0)
    not_helpful = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["guide", "day", "venue"], name="unique_guide_day_venue")]


class SearchStat(models.Model):
    """How often a search was made on a day, and how many results it found the last time."""

    query = models.CharField(max_length=100)
    venue = models.ForeignKey("venues.Venue", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # "staff" or "manager": „Често търсено“ on the home page uses only the staff's searches.
    role = models.CharField(max_length=10, blank=True, default="")
    day = models.DateField(db_index=True)
    count = models.PositiveIntegerField(default=0)
    results = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["query", "day", "venue", "role"], name="unique_query_day_venue_role")]


class Vote(models.Model):
    """The answer of one venue account to „Помогна ли ви?“ on one guide, so it is asked only once.

    The account belongs to a venue, not to a person. Deleted with the stats after 365 days.
    """

    guide = models.ForeignKey("guides.GuidePage", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    helpful = models.BooleanField()
    # With „Не“: what was missing or unclear (required), shown to the editors in Статистика.
    reason = models.TextField(blank=True, default="")
    day = models.DateField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["guide", "user"], name="unique_vote_guide_user")]


class Seen(models.Model):
    """When a venue account first opened a post: it is „Ново“ for that account until then, and
    the editors see which venues opened it. Kept as long as the post and the account exist."""

    guide = models.ForeignKey("guides.GuidePage", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["guide", "user"], name="unique_seen_guide_user")]


class Ack(models.Model):
    """„Прочетох“ of a venue account on a post that asks for it (GuidePage.needs_ack)."""

    guide = models.ForeignKey("guides.GuidePage", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["guide", "user"], name="unique_ack_guide_user")]
