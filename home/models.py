from django.db import models
from django.db.models import Q
from django.utils import timezone

from wagtail.admin.panels import FieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting
from wagtail.models import Page


# „Нови за вас“ shows this many cards; the rest are counted.
UNREAD_SHOWN = 12


class HomePage(Page):
    intro = models.CharField(
        "Подзаглавие",
        max_length=255,
        blank=True,
        help_text="Кратък текст под заглавието на началната страница.",
    )

    content_panels = Page.content_panels + [FieldPanel("intro")]

    parent_page_types = ["wagtailcore.Page"]
    subpage_types = ["guides.DepartmentPage"]
    max_count = 1

    class Meta:
        verbose_name = "Начална страница"

    def get_context(self, request, *args, **kwargs):
        """Staff-first: what people search for and read most, then a light overview per department."""
        from guides.audience import visible_guides
        from guides.models import DepartmentPage
        from stats.reading import confirms, unread
        from stats.reports import highlights, popular_for
        from venues.access import is_reader

        context = super().get_context(request, *args, **kwargs)
        # Only what this user may see (venue, role), see guides/audience.py.
        guides = visible_guides(request.user).descendant_of(self)

        departments = list(DepartmentPage.objects.live().child_of(self))
        for department in departments:
            in_department = guides.descendant_of(department)
            department.guide_count = in_department.count()
            department.highlights = highlights(in_department)

        context["departments"] = departments
        context["popular_searches"] = popular_for(request.user)
        # Every post appears once: „Нови за вас“ (venue accounts: not opened yet or, for a manager,
        # still to confirm, those first), then „Важно“, then „Последни публикации“.
        shown = []
        if is_reader(request.user):
            context["confirms"] = confirms(request.user)
            order = ("-needs_ack", "-last_published_at") if context["confirms"] else ("-last_published_at",)
            fresh = list(unread(request.user, guides).order_by(*order))
            context["unread"] = fresh[:UNREAD_SHOWN]
            context["unread_count"] = len(fresh)
            context["unread_more"] = len(fresh) - len(context["unread"])
            shown = [g.pk for g in fresh]
        today = timezone.localdate()
        pinned = list(
            guides.filter(is_pinned=True)
            .filter(Q(pinned_until__isnull=True) | Q(pinned_until__gte=today))
            .exclude(pk__in=shown)
            .order_by("-last_published_at")[:6]
        )
        context["pinned"] = pinned
        latest = guides.exclude(pk__in=shown + [g.pk for g in pinned]).order_by("-last_published_at")
        context["latest"] = latest[:6]
        return context


@register_setting(icon="image")
class SiteBranding(BaseSiteSetting):
    site_name = models.CharField(
        "Име на сайта", max_length=100, default="Информационен център"
    )
    logo = models.ForeignKey(
        "wagtailimages.Image",
        verbose_name="Лого",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Препоръчително: PNG или SVG с прозрачен фон, височина поне 120px.",
    )
    footer_text = models.CharField(
        "Текст в долната част",
        max_length=255,
        blank=True,
        help_text="Напр. „Не намирате отговор? Обадете се на ИТ: вътр. 123“.",
    )

    panels = [FieldPanel("site_name"), FieldPanel("logo"), FieldPanel("footer_text")]

    class Meta:
        verbose_name = "Лого и име на сайта"
