import modelcluster.fields
from django.db import migrations, models

OLD_KEYS = ("for_all_staff", "for_all_managers", "staff_venues", "manager_venues")


def to_mode(for_all_staff, for_all_managers, staff, managers, all_venues):
    """Old audience → (audience, venue ids). A post that mixed staff of some venues with managers
    of others keeps only the staff part: nobody gets to see more than before."""
    if for_all_staff:
        return "all", []
    if staff:
        return "staff", staff
    if for_all_managers:
        return "managers", all_venues
    return "managers", managers


def from_mode(audience, venues):
    """(audience, venue ids) → the old four values."""
    if audience == "all":
        return True, False, [], []
    if audience == "staff":
        return False, False, venues, []
    return False, False, [], venues


def _revisions(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Revision = apps.get_model("wagtailcore", "Revision")
    content_type = ContentType.objects.filter(app_label="guides", model="guidepage").first()
    return Revision.objects.filter(content_type=content_type) if content_type else Revision.objects.none()


def _ids(through, field_id):
    rows = {}
    for page_id, venue_id in through.objects.values_list("guidepage_id", field_id):
        rows.setdefault(page_id, []).append(venue_id)
    return rows


def forward(apps, schema_editor):
    GuidePage = apps.get_model("guides", "GuidePage")
    Venue = apps.get_model("venues", "Venue")
    all_venues = list(Venue.objects.values_list("pk", flat=True))
    staff = _ids(GuidePage._meta.get_field("staff_venues").remote_field.through, "venue_id")
    managers = _ids(GuidePage._meta.get_field("manager_venues").remote_field.through, "venue_id")
    through = GuidePage._meta.get_field("venues").remote_field.through
    for page in GuidePage.objects.all():
        audience, venues = to_mode(page.for_all_staff, page.for_all_managers,
                                   staff.get(page.pk, []), managers.get(page.pk, []), all_venues)
        GuidePage.objects.filter(pk=page.pk).update(audience=audience)
        through.objects.bulk_create([through(guidepage_id=page.pk, venue_id=v) for v in venues])
    # Old revisions too, so publishing one (e.g. „Върни на сайта“) can't fall back to „Всички обекти“.
    for revision in _revisions(apps):
        content = revision.content
        if "audience" in content:
            continue
        content["audience"], content["venues"] = to_mode(
            content.get("for_all_staff", True), content.get("for_all_managers", False),
            content.get("staff_venues") or [], content.get("manager_venues") or [], all_venues,
        )
        for key in OLD_KEYS:
            content.pop(key, None)
        revision.save(update_fields=["content"])


def backward(apps, schema_editor):
    GuidePage = apps.get_model("guides", "GuidePage")
    venues = _ids(GuidePage._meta.get_field("venues").remote_field.through, "venue_id")
    staff_through, manager_through = GuidePage._meta.get_field("staff_venues").remote_field.through, GuidePage._meta.get_field("manager_venues").remote_field.through
    for page in GuidePage.objects.all():
        all_staff, all_managers, staff, managers = from_mode(page.audience, venues.get(page.pk, []))
        GuidePage.objects.filter(pk=page.pk).update(for_all_staff=all_staff, for_all_managers=all_managers)
        staff_through.objects.bulk_create([staff_through(guidepage_id=page.pk, venue_id=v) for v in staff])
        manager_through.objects.bulk_create([manager_through(guidepage_id=page.pk, venue_id=v) for v in managers])
    for revision in _revisions(apps):
        content = revision.content
        if "audience" not in content:
            continue
        values = from_mode(content.pop("audience"), content.pop("venues", None) or [])
        content.update(zip(OLD_KEYS, values))
        revision.save(update_fields=["content"])


class Migration(migrations.Migration):

    dependencies = [
        ("guides", "0008_editor_groups"),
        ("venues", "0003_venue_accounts"),
        ("wagtailcore", "0097_baselogentry_uuid_action_timestamp_indexes"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="guidepage",
            name="audience",
            field=models.CharField(choices=[("all", "Всички обекти"), ("staff", "Служителите на избрани обекти"), ("managers", "Само управителите на избрани обекти")], default="all", max_length=10, verbose_name="Кой я вижда"),
        ),
        migrations.AddField(
            model_name="guidepage",
            name="venues",
            field=modelcluster.fields.ParentalManyToManyField(blank=True, related_name="posts", to="venues.venue", verbose_name="Избрани обекти"),
        ),
        migrations.RunPython(forward, backward),
        migrations.RemoveField(model_name="guidepage", name="for_all_managers"),
        migrations.RemoveField(model_name="guidepage", name="for_all_staff"),
        migrations.RemoveField(model_name="guidepage", name="manager_venues"),
        migrations.RemoveField(model_name="guidepage", name="staff_venues"),
    ]
