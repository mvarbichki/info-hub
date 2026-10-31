"""Users (superuser only): every account in one place: editors of departments and venue accounts."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from venues.access import create_account, login_base, set_venue_role
from venues.models import ROLE_CHOICES, Venue

from ..access import create_editor, departments_for, set_department
from ..forms import EDITOR, USER_ROLES, UserForm
from ..models import must_change_password, set_must_change_password
from .common import back_to_list, head_context, superuser_required


ROLE_LABELS = dict(ROLE_CHOICES)


def _managed_user(request, pk):
    """Any account except superusers (managed in /admin/) and yourself."""
    user = get_object_or_404(get_user_model().objects.select_related("venue_account__venue"), pk=pk)
    if user.is_superuser or user == request.user:
        raise Http404
    return user


def _describe(account):
    """Role and place for the table: („Управител на обект“, „Перник“) …"""
    venue_account = getattr(account, "venue_account", None)
    if account.is_superuser:
        return "admin", "Администратор", "всички раздели"
    if venue_account is not None:
        return venue_account.role, ROLE_LABELS[venue_account.role], venue_account.venue.name
    managed = ", ".join(d.title for d in departments_for(account))
    return EDITOR, "Редактор", managed or "– няма раздел –"


@superuser_required
def users(request):
    initial = {"role": request.GET.get("new_role", EDITOR), "venue": request.GET.get("new_venue")}
    form = UserForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        if data["role"] == EDITOR:
            user = create_editor(data["username"], data["department"], data["password"])
            password = data["password"] or user.username
            messages.success(request, f"Създаден е редактор „{user.username}“ за {data['department'].title}. Временна парола: „{password}“. При първия вход ще трябва да я смени.")
        else:
            user = create_account(data["username"], data["venue"], data["role"], data["password"])
            messages.success(request, f"Създаден е „{user.username}“: {ROLE_LABELS[data['role']].lower()} {data['venue'].name}. Кажете паролата в обекта.")
        return redirect(f"{reverse('dashboard:users')}?venue={data['venue'].pk}" if data.get("venue") and data["role"] != EDITOR else "dashboard:users")

    role_filter = request.GET.get("role", "")
    venue_filter = request.GET.get("venue", "")
    query = request.GET.get("q", "").strip()
    rows = []
    for account in get_user_model().objects.select_related("venue_account__venue").order_by("username"):
        kind, role_label, place = _describe(account)
        if role_filter and kind != role_filter:
            continue
        if venue_filter and (kind not in ROLE_LABELS or str(account.venue_account.venue_id) != venue_filter):
            continue
        if query and query.casefold() not in account.username.casefold() and query.casefold() not in place.casefold():
            continue
        account.kind, account.role_label, account.place = kind, role_label, place
        account.must_change = kind == EDITOR and must_change_password(account)
        account.venue_stopped = kind in ROLE_LABELS and not account.venue_account.venue.is_active
        rows.append(account)
    order = {"admin": 0, EDITOR: 1, "staff": 2, "manager": 3}
    rows.sort(key=lambda a: (min(order[a.kind], 2), a.place.casefold() if a.kind in ROLE_LABELS else "", order[a.kind], a.username.casefold()))

    venues = list(Venue.objects.all())
    taken = sorted(name.lower() for name in get_user_model().objects.values_list("username", flat=True))
    context = head_context(request)
    context.update({
        "form": form,
        "accounts": rows,
        "venues": venues,
        "roles": USER_ROLES,
        "role_filter": role_filter,
        "venue_filter": venue_filter,
        "query": query,
        "filtered": bool(role_filter or venue_filter or query),
        "login_bases": {str(v.pk): login_base(v.name) for v in venues},
        "taken_usernames": taken,
    })
    return TemplateResponse(request, "dashboard/users.html", context)


@superuser_required
def edit_user(request, pk):
    """Login name, and the venue + role of a venue account or the department of an editor."""
    account = _managed_user(request, pk)
    venue_account = getattr(account, "venue_account", None)
    if venue_account is not None:
        initial = {"role": venue_account.role, "venue": venue_account.venue_id}
    else:
        current = departments_for(account).first()
        initial = {"role": EDITOR, "department": current.pk if current else None}
    initial["username"] = account.username
    form = UserForm(request.POST or None, user=request.user, account=account, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        if data["username"] != account.username:
            account.username = data["username"]
            account.save(update_fields=["username"])
        if venue_account is not None:
            forgotten = set_venue_role(account, data["venue"], data["role"])
            note = " Потвържденията му „Прочетох“ (при друг обект – и отворените публикации) започват отначало." if forgotten else ""
            messages.success(request, f"„{account.username}“: {ROLE_LABELS[data['role']].lower()} {data['venue'].name}.{note}")
        else:
            set_department(account, data["department"])
            messages.success(request, f"„{account.username}“: редактор на {data['department'].title}.")
        return redirect("dashboard:users")
    context = head_context(request)
    context.update({"form": form, "account": account, "venue_account": venue_account})
    return TemplateResponse(request, "dashboard/user_edit.html", context)


@superuser_required
def user_password(request, pk):
    """Set or change the password of a venue account. It is logged out everywhere."""
    account = _managed_user(request, pk)
    venue_account = getattr(account, "venue_account", None)
    if venue_account is None:
        raise Http404  # editors: „Нулирай парола“
    form = SetPasswordForm(account, request.POST or None)
    if form.is_bound and form.is_valid():
        form.save()  # a new password logs out every session of the account
        messages.success(request, f"Паролата на „{account.username}“ ({venue_account.venue.name}) е сменена. Там трябва да се влезе отново с новата парола.")
        return redirect("dashboard:users")
    context = head_context(request)
    context.update({"account": account, "venue_account": venue_account, "role_label": ROLE_LABELS[venue_account.role], "form": form})
    return TemplateResponse(request, "dashboard/user_password.html", context)


@superuser_required
@require_POST
def reset_password(request, pk):
    user = _managed_user(request, pk)
    if hasattr(user, "venue_account"):
        raise Http404  # venue accounts get a real password, see user_password
    user.set_password(user.username)
    user.save()
    set_must_change_password(user, True)
    messages.success(request, f"Паролата на „{user.username}“ е нулирана на „{user.username}“. При следващия вход ще трябва да я смени.")
    return redirect("dashboard:users")


@superuser_required
@require_POST
def toggle_user(request, pk):
    user = _managed_user(request, pk)
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    messages.success(request, f"„{user.username}“ е {'активиран' if user.is_active else 'спрян (не може да влиза)'}.")
    return back_to_list(request, "dashboard:users")


@superuser_required
@require_POST
def delete_user(request, pk):
    user = _managed_user(request, pk)
    username = user.username
    user.delete()
    messages.success(request, f"Потребителят „{username}“ е изтрит.")
    return back_to_list(request, "dashboard:users")
