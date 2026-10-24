from django.db import migrations


def remove_word_originals(apps, schema_editor):
    """The uploaded Word files were kept in this collection. Their files on disk are removed by
    the nightly cleanup_media (files without a database row)."""
    Collection = apps.get_model("wagtailcore", "Collection")
    Document = apps.get_model("wagtaildocs", "Document")
    for collection in Collection.objects.filter(name="Оригинални файлове"):
        Document.objects.filter(collection=collection).delete()
        # A tree node: let Wagtail's own model remove it, so the tree stays consistent.
        from wagtail.models import Collection as LiveCollection

        LiveCollection.objects.get(pk=collection.pk).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("guides", "0004_link_department_collections"),
        ("wagtaildocs", "0014_alter_document_file_size"),
    ]

    operations = [
        migrations.RenameField("guidepage", "imported_media", "uploaded_media"),
        migrations.RemoveField("guidepage", "source_document"),
        migrations.RunPython(remove_word_originals, migrations.RunPython.noop),
    ]
