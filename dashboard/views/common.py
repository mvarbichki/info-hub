"""Shared by the /manage/ views: access decorators and small helpers."""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme

from ..access import can_manage, departments_for, is_editor
from ..models import must_change_password


def editor_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not is_editor(request.user):
            # E.g. the venue account on /manage/: offer the login form for another user.
            return redirect_to_login(request.get_full_path())
        if must_change_password(request.user):
            messages.info(request, "Моля, сменете временната си парола, преди да продължите.")
            return redirect("dashboard:password")
        return view(request, *args, **kwargs)

    return wrapper


def superuser_required(view):
    @wraps(view)
    @editor_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def back_to_list(request, default="dashboard:index"):
    """Redirect to the posted "next" address (the list with its filters and page), else the default."""
    target = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect(default)


def managed_page(request, model, pk):
    """The page, if it lies in one of the user's departments (404 otherwise)."""
    page = get_object_or_404(model, pk=pk)
    if not can_manage(request.user, page):
        raise Http404
    return page


def head_context(request):
    departments = list(departments_for(request.user))
    return {
        "departments": departments,
        "managed_title": "" if request.user.is_superuser else ", ".join(d.title for d in departments),
    }
