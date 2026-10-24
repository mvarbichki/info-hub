"""Wagtail admin user forms without required name/e-mail.

Accounts are per department or per venue, not per person, so first name, last name and
e-mail are optional everywhere in /admin/.
"""
from wagtail.admin.forms.account import NameEmailForm
from wagtail.users.forms import UserCreationForm, UserEditForm
from wagtail.users.views.users import UserViewSet

OPTIONAL = ("first_name", "last_name", "email")


def _optional(form):
    for name in OPTIONAL:
        if name in form.fields:
            form.fields[name].required = False


class OptionalUserCreationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _optional(self)


class OptionalUserEditForm(UserEditForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _optional(self)


class OptionalNameEmailForm(NameEmailForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _optional(self)


class InfoHubUserViewSet(UserViewSet):
    def get_form_class(self, for_update=False):
        return OptionalUserEditForm if for_update else OptionalUserCreationForm
