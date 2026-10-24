from django.db import migrations


def remove_admin_access(apps, schema_editor):
    """Department moderators work only in /manage/; the Wagtail admin is for the superuser."""
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    access_admin = Permission.objects.filter(content_type__app_label="wagtailadmin", codename="access_admin").first()
    if access_admin:
        for group in Group.objects.filter(name__endswith="– модератори"):
            group.permissions.remove(access_admin)


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0001_initial"),
        ("wagtailadmin", "0001_create_admin_access_permissions"),
    ]

    operations = [migrations.RunPython(remove_admin_access, migrations.RunPython.noop)]
