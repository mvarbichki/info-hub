"""Login, logout and changing your own password."""

import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator

from venues.access import is_reader

from ..access import is_editor
from ..forms import LoginForm
from ..models import must_change_password, set_must_change_password

EDITOR_PAGE = re.compile(r"^/manage/(new|\d+)/$")
LOGOUT_PAGE = re.compile(r"^/(manage|admin)/logout/")


def client_ip(request):
    """The visitor's address. Behind our own proxy (Docker: nginx) every request comes from the
    proxy, so it passes the visitor's address in a header (INFOHUB_CLIENT_IP_HEADER, e.g.
    HTTP_X_REAL_IP); otherwise one throttle counter would be shared by all venues."""
    header = settings.INFOHUB_CLIENT_IP_HEADER
    return (request.META.get(header) if header else "") or request.META.get("REMOTE_ADDR", "")


@method_decorator(login_not_required, name="dispatch")  # dispatch is overridden below
class Login(LoginView):
    """The one login page of the site (also for /admin/). Venue accounts land on the site,
    departments in /manage/.

    Somebody logged in is sent on, unless a page they can't open sent them here ("next"): then the
    form is shown to log in as another user (and no redirect loop happens).
    After INFOHUB_LOGIN_ATTEMPTS failed logins from one address, it waits 15 minutes.
    """

    template_name = "dashboard/login.html"
    form_class = LoginForm
    LOCK_SECONDS = 15 * 60

    def dispatch(self, request, *args, **kwargs):
        if request.method == "GET" and LOGOUT_PAGE.match(request.GET.get(self.redirect_field_name, "")):
            return redirect("login")  # "log in, then log out" is never meant (an old double logout)
        self.redirect_authenticated_user = not request.GET.get(self.redirect_field_name)
        if request.user.is_authenticated and not self.redirect_authenticated_user:
            list(messages.get_messages(request))  # e.g. Wagtail's English "no permission"; the page says it in Bulgarian
        return super().dispatch(request, *args, **kwargs)

    @property
    def attempts_key(self):
        return "login-failures:" + client_ip(self.request)

    def post(self, request, *args, **kwargs):
        if cache.get(self.attempts_key, 0) >= settings.INFOHUB_LOGIN_ATTEMPTS:
            return self.render_to_response(self.get_context_data(locked=True))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        cache.set(self.attempts_key, cache.get(self.attempts_key, 0) + 1, self.LOCK_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        response = super().form_valid(form)
        cache.delete(self.attempts_key)
        if is_reader(self.request.user):
            self.request.session.set_expiry(settings.INFOHUB_VENUE_SESSION_DAYS * 24 * 3600)
        return response

    def get_redirect_url(self):
        url = super().get_redirect_url()
        return "" if LOGOUT_PAGE.match(url) else url

    def get_default_redirect_url(self):
        return reverse("dashboard:index") if is_editor(self.request.user) else "/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Sent here from the post editor: a save while logged out lands here, the post unsaved.
        context["from_editor"] = not self.request.user.is_authenticated and bool(EDITOR_PAGE.match(context.get("next") or ""))
        return context


@method_decorator(login_not_required, name="dispatch")
class Logout(LogoutView):
    """Used for /manage/logout/, the manage bar and the Wagtail admin's log out: back to the login page.

    Open to everybody: a double click on „Изход“ sends a second logout after the first one, and that
    must not land on the login page with "next=/manage/logout/" (after the next login the browser
    would open the logout address and get an empty 405 page). A plain visit (GET) logs nobody out
    (that needs the form's CSRF token); it only goes to the login page.
    """

    http_method_names = ["get", "post", "options"]
    next_page = "login"

    def get(self, request, *args, **kwargs):
        return redirect("login")

    def post(self, request, *args, **kwargs):
        was_logged_in = request.user.is_authenticated
        response = super().post(request, *args, **kwargs)
        if was_logged_in:
            messages.success(request, "Излязохте успешно.")
        return response


@method_decorator(login_required, name="dispatch")
class PasswordChange(PasswordChangeView):
    template_name = "dashboard/password.html"
    success_url = reverse_lazy("dashboard:index")

    def dispatch(self, request, *args, **kwargs):
        # Venue passwords are set by the superuser only (Потребители).
        if not is_editor(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        set_must_change_password(self.request.user, False)
        messages.success(self.request, "Паролата е сменена.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["forced"] = must_change_password(self.request.user)
        return context
