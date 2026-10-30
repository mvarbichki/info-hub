from datetime import timedelta

from django.core.paginator import Paginator
from django.db import models
from django.utils import timezone

from django import forms
from django.core.exceptions import ValidationError
from modelcluster.fields import ParentalManyToManyField
from wagtail.admin.panels import FieldPanel, FieldRowPanel, MultiFieldPanel
from wagtail.fields import StreamField
from wagtail.models import Page
from wagtail.search import index

from .blocks import GuideStreamBlock

COLOR_CHOICES = [
    ("blue", "Син"),
    ("green", "Зелен"),
    ("purple", "Лилав"),
    ("orange", "Оранжев"),
    ("red", "Червен"),
    ("teal", "Тюркоазен"),
]

ICON_CHOICES = [
    ("computer", "Компютър"),
    ("people", "Хора"),
    ("megaphone", "Мегафон"),
    ("info", "Информация"),
    ("tools", "Инструменти"),
    ("book", "Книга"),
]

KIND_CHOICES = [
    ("guide", "Ръководство"),
    ("news", "Новина"),
    ("campaign", "Кампания"),
]

AUDIENCE_ALL, AUDIENCE_STAFF, AUDIENCE_MANAGERS = "all", "staff", "managers"
AUDIENCE_CHOICES = [
    (AUDIENCE_ALL, "Всички обекти"),
    (AUDIENCE_STAFF, "Служителите на избрани обекти"),
    (AUDIENCE_MANAGERS, "Само управителите на избрани обекти"),
]

RECENT_DAYS = 7
# A venue account sees a post as „Ново“ (and in „Нови за вас“) until it opens it, for this many days.
UNREAD_DAYS = 30


def paginate(request, queryset, per_page=20):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


class DepartmentPage(Page):
    description = models.CharField("Кратко описание", max_length=255, blank=True)
    color = models.CharField("Цвят", max_length=20, choices=COLOR_CHOICES, default="blue")
    icon = models.CharField("Икона", max_length=20, choices=ICON_CHOICES, default="info")
    # Shown to staff who answer „Не“ to „Помогна ли ви?“ on one of its posts.
    contact = models.CharField("Връзка при проблем", max_length=255, blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("description"),
        FieldPanel("contact"),
        FieldRowPanel([FieldPanel("color"), FieldPanel("icon")]),
    ]

    parent_page_types = ["home.HomePage"]
    subpage_types = ["guides.CategoryPage", "guides.GuidePage"]

    class Meta:
        verbose_name = "Раздел"
        verbose_name_plural = "Раздели"

    def get_context(self, request, *args, **kwargs):
        from .audience import visible_guides

        context = super().get_context(request, *args, **kwargs)
        visible = visible_guides(request.user)
        guides = visible.descendant_of(self)

        kind = request.GET.get("type")
        if kind in dict(KIND_CHOICES):
            guides = guides.filter(kind=kind)
        else:
            kind = ""

        categories = list(CategoryPage.objects.live().child_of(self))
        for category in categories:
            category.guide_count = visible.child_of(category).count()

        context["categories"] = categories
        context["kinds"] = KIND_CHOICES
        context["active_kind"] = kind
        context["guides"] = paginate(request, guides.order_by("-last_published_at"))
        return context


class DepartmentMedia(models.Model):
    """The media folder (collection) of a department. Kept outside the page so it isn't part of
    page revisions, and survives renaming the department."""

    department = models.OneToOneField(DepartmentPage, on_delete=models.CASCADE, related_name="media")
    collection = models.OneToOneField("wagtailcore.Collection", on_delete=models.CASCADE, related_name="+")

    class Meta:
        verbose_name = "Папка на раздел"


class DocumentPreview(models.Model):
    """A PDF copy of an uploaded Word/Excel/PowerPoint file (guides/previews.py), shown in the post
    like a PDF. Served with the same checks as the file itself; deleted with it."""

    document = models.OneToOneField("wagtaildocs.Document", on_delete=models.CASCADE, related_name="preview")
    file = models.FileField(upload_to="previews/")

    class Meta:
        verbose_name = "PDF копие на файл"


class CategoryPage(Page):
    description = models.CharField("Кратко описание", max_length=255, blank=True)

    content_panels = Page.content_panels + [FieldPanel("description")]

    parent_page_types = ["guides.DepartmentPage"]
    subpage_types = ["guides.GuidePage"]

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

    @property
    def department(self):
        return self.get_parent().specific

    def get_context(self, request, *args, **kwargs):
        from .audience import visible_guides

        context = super().get_context(request, *args, **kwargs)
        guides = visible_guides(request.user).child_of(self).order_by("-last_published_at")
        context["guides"] = paginate(request, guides)
        return context


class GuidePage(Page):
    kind = models.CharField("Вид", max_length=20, choices=KIND_CHOICES, default="guide")
    summary = models.TextField(
        "Кратко описание",
        max_length=300,
        blank=True,
        help_text="1–2 изречения. Показва се в списъците и в резултатите от търсене.",
    )
    body = StreamField(GuideStreamBlock(), verbose_name="Съдържание", blank=True)
    is_pinned = models.BooleanField(
        "Покажи в „Важно“", default=False, help_text="Показва се най-горе на началната страница."
    )
    pinned_until = models.DateField(
        "Важно до", null=True, blank=True, help_text="След тази дата спира да се показва в „Важно“."
    )
    # Lower-cased plain text of the published content, used by the public search.
    search_text = models.TextField(editable=False, blank=True, default="")
    # Images and documents uploaded for this post in /manage/ ({"images": [ids], "documents": [ids]}).
    # Deleted with the post, or when an edit no longer uses them (see guides/publishing.py).
    uploaded_media = models.JSONField(default=dict, blank=True, editable=False)
    # Who sees the post (see guides/audience.py): everybody, or the chosen venues' staff (with their
    # managers), or only the chosen venues' managers. Never a mix of the two.
    audience = models.CharField("Кой я вижда", max_length=10, choices=AUDIENCE_CHOICES, default=AUDIENCE_ALL)
    venues = ParentalManyToManyField("venues.Venue", blank=True, related_name="posts", verbose_name="Избрани обекти")
    # The venue accounts confirm with „Прочетох“; the editors see who did (stats.Ack).
    needs_ack = models.BooleanField("Искай „Прочетох“", default=False)

    content_panels = Page.content_panels + [
        FieldPanel("kind"),
        FieldPanel("summary"),
        FieldPanel("body"),
        MultiFieldPanel(
            [FieldRowPanel([FieldPanel("is_pinned"), FieldPanel("pinned_until")])],
            heading="Важно на началната страница",
        ),
        MultiFieldPanel(
            [
                FieldPanel("audience", widget=forms.RadioSelect),
                FieldPanel("venues", widget=forms.CheckboxSelectMultiple),
            ],
            heading="Кой я вижда",
        ),
        FieldPanel("needs_ack"),
    ]

    search_fields = Page.search_fields + [
        index.SearchField("summary"),
        index.SearchField("body"),
    ]

    parent_page_types = ["guides.DepartmentPage", "guides.CategoryPage"]
    subpage_types = []

    class Meta:
        verbose_name = "Публикация"
        verbose_name_plural = "Публикации"

    def clean(self):
        super().clean()
        if self.audience != AUDIENCE_ALL and not self.venues.exists():
            raise ValidationError("Изберете поне един обект или „Всички обекти“.")

    def save(self, *args, **kwargs):
        parts = [self.title, self.summary]
        parts += self.body.stream_block.get_searchable_content(self.body)
        self.search_text = " ".join(p for p in parts if p).lower()
        return super().save(*args, **kwargs)

    @property
    def department(self):
        return DepartmentPage.objects.ancestor_of(self).first()

    @property
    def is_draft(self):
        """Saved, but never published (an archived post was published before)."""
        return not self.live and self.first_published_at is None

    @property
    def is_new(self):
        return bool(self.first_published_at) and (
            timezone.now() - self.first_published_at < timedelta(days=RECENT_DAYS)
        )

    @property
    def is_updated(self):
        if not (self.first_published_at and self.last_published_at) or self.is_new:
            return False
        recently = timezone.now() - self.last_published_at < timedelta(days=RECENT_DAYS)
        return recently and self.last_published_at - self.first_published_at > timedelta(hours=1)

    def serve(self, request, *args, **kwargs):
        from django.http import Http404

        from stats.reading import mark_seen
        from stats.tracking import count_view, counted_reader, is_prefetch
        from venues.access import is_reader

        from .audience import can_see

        # (Previews don't come here: Wagtail renders them with serve_preview, for editors only.)
        # A post for other venues (or only for venue managers) doesn't exist for this user.
        if not can_see(request.user, self):
            raise Http404
        response = super().serve(request, *args, **kwargs)
        if request.method == "GET" and is_reader(request.user) and not is_prefetch(request):
            mark_seen(self, request.user)  # no longer „Ново“ for this account, also on the training PCs
            me = counted_reader(request)
            if me:
                count_view(self, me)
        return response

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["headings"] = [
            (block.id, block.value) for block in self.body if block.block_type == "heading"
        ]
        context["my_vote"] = context["my_ack"] = None
        if request.user.is_authenticated:
            from dashboard.access import can_manage, is_editor
            from stats.models import Ack, Vote
            from venues.access import is_reader

            from .audience import summary

            context["can_edit"] = is_editor(request.user) and can_manage(request.user, self)
            if is_editor(request.user):
                context["audience_summary"] = summary(self)
            if not is_editor(request.user):
                context["help_department"] = self.department  # „Не“: who to ask
            if is_reader(request.user):
                context["my_vote"] = Vote.objects.filter(guide=self, user=request.user).values_list("helpful", flat=True).first()
                if self.needs_ack:
                    context["my_ack"] = Ack.objects.filter(guide=self, user=request.user).values_list("at", flat=True).first()
        return context
