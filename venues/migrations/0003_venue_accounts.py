import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def to_accounts(apps, schema_editor):
    """The fixed pair (Venue.staff, Venue.manager) becomes VenueAccount rows. A venue whose
    accounts were all stopped becomes a stopped venue, and its accounts active again."""
    Venue = apps.get_model("venues", "Venue")
    VenueAccount = apps.get_model("venues", "VenueAccount")
    for venue in Venue.objects.all():
        users = [(role, user) for role, user in (("staff", venue.staff), ("manager", venue.manager)) if user]
        for role, user in users:
            VenueAccount.objects.create(user=user, venue=venue, role=role)
        if users and not any(user.is_active for _, user in users):
            venue.is_active = False
            venue.save(update_fields=["is_active"])
            for _, user in users:
                user.is_active = True
                user.save(update_fields=["is_active"])


class Migration(migrations.Migration):

    dependencies = [
        ("venues", "0002_training_venue"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="venue",
            name="is_active",
            field=models.BooleanField(default=True, verbose_name="Работи"),
        ),
        migrations.CreateModel(
            name="VenueAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("staff", "Служители на обект"), ("manager", "Управител на обект")], max_length=10, verbose_name="Роля")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="venue_account", to=settings.AUTH_USER_MODEL)),
                ("venue", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="accounts", to="venues.venue")),
            ],
            options={
                "verbose_name": "Потребител на обект",
                "verbose_name_plural": "Потребители на обекти",
                "ordering": ["venue__name", "-role", "user__username"],
            },
        ),
        migrations.RunPython(to_accounts, migrations.RunPython.noop),
        migrations.RemoveField(model_name="venue", name="manager"),
        migrations.RemoveField(model_name="venue", name="staff"),
    ]
