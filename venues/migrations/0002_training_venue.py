from django.conf import settings
from django.db import migrations

VENUE_GROUP = "Обекти – само преглед"


def training_venue(apps, schema_editor):
    """The old shared venue login `staff` becomes the staff account of the training venue „Обучение“,
    with a new `manager` account (no password yet). Same as venues.access.training_venue()."""
    Venue = apps.get_model("venues", "Venue")
    Group = apps.get_model("auth", "Group")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    if Venue.objects.filter(is_training=True).exists():
        return
    group, _ = Group.objects.get_or_create(name=VENUE_GROUP)

    def account(name):
        user = User.objects.filter(username=name).first()
        if user is not None and (user.is_superuser or user.groups.exclude(name=VENUE_GROUP).exists()):
            name, user = f"training_{name}", None
        if user is None:
            user = User.objects.create(username=name, password="!")  # "!" = no usable password
        user.groups.add(group)
        return user

    Venue.objects.create(name="Обучение", staff=account("staff"), manager=account("manager"), is_training=True)


class Migration(migrations.Migration):

    dependencies = [
        ("venues", "0001_initial"),
        ("dashboard", "0003_venue_group"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(training_venue, migrations.RunPython.noop)]
