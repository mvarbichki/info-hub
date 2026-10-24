from django.conf import settings
from django.db import migrations

VENUE_GROUP = "Обекти – само преглед"


def add_venue_group(apps, schema_editor):
    """A group without permissions for the venues' shared account, so its rights show in the admin."""
    Group = apps.get_model("auth", "Group")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    group, _ = Group.objects.get_or_create(name=VENUE_GROUP)
    for user in User.objects.filter(username="staff"):  # the shared venue login of that time
        user.groups.add(group)


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0002_department_groups_without_admin"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(add_venue_group, migrations.RunPython.noop)]
