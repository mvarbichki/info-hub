from django.db import migrations


def remove(apps, schema_editor):
    """Wagtail's own starter groups „Moderators“ and „Editors“ give access to /admin/ and are not
    used here (editors are in „<Отдел> – редактори“). Removed while nobody is in them."""
    Group = apps.get_model("auth", "Group")
    for group in Group.objects.filter(name__in=["Moderators", "Editors"]):
        if not group.user_set.exists():
            group.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0003_venue_group"),
        # After every Wagtail migration that gives these groups permissions (on a fresh database).
        ("wagtailcore", "0097_baselogentry_uuid_action_timestamp_indexes"),
        ("wagtailadmin", "0006_formstate"),
        ("wagtailimages", "0027_image_description"),
        ("wagtaildocs", "0014_alter_document_file_size"),
    ]

    operations = [migrations.RunPython(remove, migrations.RunPython.noop)]
