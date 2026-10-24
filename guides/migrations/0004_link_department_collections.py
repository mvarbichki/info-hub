from django.db import migrations


def link_by_name(apps, schema_editor):
    """Until now a department's collection was found by having the same name as the department."""
    DepartmentPage = apps.get_model("guides", "DepartmentPage")
    DepartmentMedia = apps.get_model("guides", "DepartmentMedia")
    Collection = apps.get_model("wagtailcore", "Collection")
    for department in DepartmentPage.objects.all():
        collection = Collection.objects.filter(name=department.title, depth=2).first()
        if collection and not DepartmentMedia.objects.filter(collection=collection).exists():
            DepartmentMedia.objects.get_or_create(department=department, defaults={"collection": collection})


class Migration(migrations.Migration):

    dependencies = [
        ("guides", "0003_departmentmedia"),
    ]

    operations = [migrations.RunPython(link_by_name, migrations.RunPython.noop)]
