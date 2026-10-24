from django.db import migrations

OLD, NEW = " – модератори", " – редактори"


def rename(apps, old, new):
    """„ИТ – модератори“ → „ИТ – редактори“ (the department users are called editors now)."""
    Group = apps.get_model("auth", "Group")
    for group in Group.objects.filter(name__endswith=old):
        name = group.name[: -len(old)] + new
        if not Group.objects.filter(name=name).exists():
            group.name = name
            group.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("guides", "0007_audience"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(lambda apps, _: rename(apps, OLD, NEW), lambda apps, _: rename(apps, NEW, OLD)),
    ]
