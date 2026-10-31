import re

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.validators import RegexValidator
from django.utils import timezone

from guides.audience import AudienceError, normalize
from guides.departments import RESERVED_SLUGS
from guides.models import COLOR_CHOICES, ICON_CHOICES, KIND_CHOICES, CategoryPage, DepartmentPage
from venues.access import USERNAME, suggest_username
from venues.models import MANAGER, ROLE_CHOICES, STAFF, Venue

from .access import departments_for


def same_name(queryset, field, value):
    """The objects whose `field` equals `value` ignoring case. In Python, because SQLite's
    case-insensitive lookups only fold Latin letters („ИТ“ ≠ „ит“ there)."""
    value = value.casefold()
    return [obj for obj in queryset.only(field) if getattr(obj, field).casefold() == value]


def place_choices(user):
    """The user's departments and their categories in one list: "ИТ", "ИТ › Принтери", ..."""
    choices = []
    for department in departments_for(user):
        choices.append((str(department.pk), department.title))
        for category in CategoryPage.objects.child_of(department):
            choices.append((str(category.pk), f"{department.title} › {category.title}"))
    return choices


GONE_VENUE = {
    "invalid_choice": "Един от избраните обекти вече не съществува (изтрит е). Презаредете страницата и изберете отново.",
    "invalid_pk_value": "Един от избраните обекти вече не съществува (изтрит е). Презаредете страницата и изберете отново.",
}


class GuideForm(forms.Form):
    """The post editor. Every error names what is wrong and what to do; edit.html shows it next to
    its part of the page (audience errors are put on `all_venues`, the picker's first field)."""

    title = forms.CharField(label="Заглавие", max_length=255, error_messages={
        "required": "Въведете заглавие.",
        "max_length": "Заглавието е твърде дълго: до %(limit_value)d знака (сега %(show_value)d).",
    })
    summary = forms.CharField(
        label="Кратко описание", max_length=300, required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="1–2 изречения. Показва се в списъците и в резултатите от търсене.",
        error_messages={"max_length": "Краткото описание е до %(limit_value)d знака (сега %(show_value)d). Съкратете го."},
    )
    place = forms.ChoiceField(label="Къде да се публикува", error_messages={
        "required": "Изберете къде да се публикува.",
        "invalid_choice": "Това място вече не съществува или нямате достъп до него. Изберете друго от списъка.",
    })
    kind = forms.ChoiceField(label="Вид", choices=KIND_CHOICES, widget=forms.RadioSelect, initial="guide", error_messages={
        "required": "Изберете вид: ръководство, новина или кампания.",
        "invalid_choice": "Изберете вид: ръководство, новина или кампания.",
    })
    is_pinned = forms.BooleanField(label="Покажи в „Важно“ на началната страница", required=False)
    pinned_until = forms.DateField(label="до", required=False, widget=forms.DateInput(attrs={"type": "date"}),
                                   error_messages={"invalid": "Въведете дата, напр. 31.12.2026."})
    # The editor's blocks as JSON (see guides/editor.py), filled in by editor.js on submit.
    body = forms.CharField(required=False, widget=forms.HiddenInput)
    # Who sees the post (guides/audience.py). The picker in edit.html, helped by audience.js.
    all_venues = forms.BooleanField(label="Всички обекти", required=False, initial=True)
    staff_venues = forms.ModelMultipleChoiceField(queryset=Venue.objects.all(), required=False, error_messages=GONE_VENUE)
    manager_venues = forms.ModelMultipleChoiceField(queryset=Venue.objects.all(), required=False, error_messages=GONE_VENUE)
    needs_ack = forms.BooleanField(label="Искай „Прочетох“ от управителите", required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["place"].choices = place_choices(user)
        # „Важно“ on the home page is shared by all departments, so only the superuser sets it.
        if not user.is_superuser:
            del self.fields["is_pinned"]
            del self.fields["pinned_until"]

    def clean_title(self):
        return " ".join(self.cleaned_data["title"].split())

    def clean_summary(self):
        return " ".join(self.cleaned_data["summary"].split())

    def clean(self):
        data = super().clean()
        if data.get("is_pinned") and data.get("pinned_until") and data["pinned_until"] < timezone.localdate():
            self.add_error("pinned_until", "Тази дата е минала. Изберете бъдеща дата или оставете полето празно.")
        if not ("staff_venues" in self.errors or "manager_venues" in self.errors):
            try:
                data["audience"] = normalize(data.get("all_venues"), data.get("staff_venues") or [], data.get("manager_venues") or [])
            except AudienceError as error:
                self.add_error("all_venues", str(error))
        return data

    def parent_page(self):
        from wagtail.models import Page

        return Page.objects.get(pk=self.cleaned_data["place"]).specific


def department_field(user, label="Раздел"):
    return forms.ModelChoiceField(label=label, queryset=departments_for(user), empty_label=None)


class CategoryForm(forms.Form):
    title = forms.CharField(label="Име на категорията", max_length=255)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"] = department_field(user)


class RenameCategoryForm(forms.Form):
    title = forms.CharField(label="Ново име", max_length=255)


class DepartmentForm(forms.Form):
    title = forms.CharField(label="Име", max_length=255)
    slug = forms.CharField(
        label="Адрес", max_length=80, required=False,
        validators=[RegexValidator(r"^[a-z0-9-]+$", "Само малки латински букви, цифри и тире, напр. finance.")],
        help_text="Латиница, напр. finance → /finance/. Празно = от името. После не се сменя.",
    )
    description = forms.CharField(label="Кратко описание", max_length=255, required=False)
    contact = forms.CharField(label="Връзка при проблем", max_length=255, required=False)
    color = forms.ChoiceField(label="Цвят", choices=COLOR_CHOICES)
    icon = forms.ChoiceField(label="Икона", choices=ICON_CHOICES)

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.department = department
        if department is not None:
            del self.fields["slug"]  # the address stays, so links keep working

    def clean_title(self):
        title = self.cleaned_data["title"]
        others = DepartmentPage.objects.all()
        if self.department is not None:
            others = others.exclude(pk=self.department.pk)
        if same_name(others, "title", title):
            raise forms.ValidationError("Вече има раздел с това име.")
        return title

    def clean_slug(self):
        slug = self.cleaned_data["slug"].lower()
        if slug in RESERVED_SLUGS:
            raise forms.ValidationError(f"Адресът „/{slug}/“ се използва от сайта. Изберете друг.")
        if slug and DepartmentPage.objects.filter(slug=slug).exists():
            raise forms.ValidationError("Вече има раздел с този адрес.")
        return slug


EDITOR = "editor"
USER_ROLES = [*ROLE_CHOICES, (EDITOR, "Редактор (публикува за раздел)")]


class UserForm(forms.Form):
    """A new account (venue staff, venue manager or editor of a department), or a changed one.

    A venue account needs a venue and a password; an editor needs a department, and gets the
    username as temporary password when none is given. When editing, the kind stays the same
    (a venue account stays a venue account), only the venue/role or the department and the
    login name change.
    """

    role = forms.ChoiceField(label="Роля", choices=USER_ROLES)
    venue = forms.ModelChoiceField(label="Обект", queryset=Venue.objects.all(), required=False, empty_label="– изберете обект –")
    username = forms.CharField(
        label="Потребителско име", max_length=40, required=False,
        help_text="Латиница, цифри, _ . -. За обект се попълва само (напр. pernik_staff), може да го смените.",
    )
    password = forms.CharField(label="Парола", max_length=128, required=False, strip=False, widget=forms.PasswordInput(render_value=True))

    def __init__(self, *args, user, account=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.account = account
        self.fields["department"] = forms.ModelChoiceField(
            label="Раздел", queryset=departments_for(user), required=False, empty_label="– изберете раздел –",
        )
        if account is not None:
            del self.fields["password"]  # changed with its own button
            self.fields["username"].required = True
            venue_account = getattr(account, "venue_account", None)
            if venue_account is not None:
                self.fields["role"].choices = ROLE_CHOICES
                del self.fields["department"]
            else:
                self.fields["role"].choices = [(EDITOR, dict(USER_ROLES)[EDITOR])]
                del self.fields["venue"]

    def clean_username(self):
        name = self.cleaned_data["username"]
        if self.account is not None and name == self.account.username:
            return name  # unchanged (may be an older name like `Staff`)
        name = name.lower()
        if name and not USERNAME.match(name):
            raise forms.ValidationError("Само малки латински букви, цифри и _ . -, от 2 до 40 знака.")
        others = get_user_model().objects.all()
        if self.account is not None:
            others = others.exclude(pk=self.account.pk)
        if name and same_name(others, "username", name):
            raise forms.ValidationError("Вече има такъв потребител.")
        return name

    def clean(self):
        data = super().clean()
        role = data.get("role")
        if role in (STAFF, MANAGER):
            if not data.get("venue"):
                self.add_error("venue", "Изберете обект.")
            elif not data.get("username") and "username" not in self.errors:
                data["username"] = suggest_username(data["venue"], role)
            if "password" in self.fields:
                if not data.get("password"):
                    self.add_error("password", "Въведете парола (кажете я в обекта).")
                elif data.get("username"):
                    try:
                        password_validation.validate_password(data["password"], get_user_model()(username=data["username"]))
                    except forms.ValidationError as error:
                        self.add_error("password", error)
        elif role == EDITOR:
            if not data.get("department"):
                self.add_error("department", "Изберете раздел.")
            if not data.get("username") and "username" not in self.errors:
                self.add_error("username", "Въведете потребителско име, напр. finance.")
        return data


class LoginForm(AuthenticationForm):
    """Login names are not case-sensitive („Pernik_staff“ = „pernik_staff“), spaces around are ignored."""

    def clean_username(self):
        name = self.cleaned_data["username"]
        matches = same_name(get_user_model().objects.all(), "username", name)
        return matches[0].username if len(matches) == 1 else name


def clean_venue_name(name):
    """„София-Младост“ / „София - Младост“ → „София – Младост“, single spaces."""
    name = " ".join(name.split())
    return re.sub(r"\s*[–—-]\s*", " – ", name).strip(" –")


class VenueForm(forms.Form):
    """A new venue or a renamed one. Its accounts are made in Потребители."""

    name = forms.CharField(
        label="Име на обекта", max_length=100,
        help_text="„Град – място“, напр. „София – Младост“. Ако в града има само един обект: само града, напр. „Перник“.",
    )

    def __init__(self, *args, venue=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.venue = venue

    def clean_name(self):
        name = clean_venue_name(self.cleaned_data["name"])
        others = Venue.objects.all()
        if self.venue is not None:
            others = others.exclude(pk=self.venue.pk)
        if not name:
            raise forms.ValidationError("Въведете име.")
        if same_name(others, "name", name):
            raise forms.ValidationError("Вече има обект с това име.")
        return name
