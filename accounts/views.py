from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import LoginForm, PasswordResetForm, RoleForm, UserCreateForm, UserEditForm
from .models import PermissionChange, Role, User
from .permissions import LockoutError, admin_remains, require_perm


@login_not_required
def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.user)
        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect("home")
    return render(request, "accounts/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    auth_logout(request)
    return redirect("login")


def _log(request, target, change):
    PermissionChange.objects.create(changed_by=request.user, target=target, change=change)


# ---------------------------------------------------------------- users


@require_perm("manage_users")
def user_list(request):
    users = User.objects.select_related("role").order_by("-is_active", "username")
    return render(request, "accounts/user_list.html", {"users": users})


@require_perm("manage_users")
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.set_password(form.cleaned_data["password1"])
        user.save()
        _log(request, f"user {user.username}", f"created with role {user.role}")
        messages.success(request, f"User {user.username} created.")
        return redirect("user_list")
    return render(request, "accounts/user_form.html", {"form": form, "title": "New user"})


@require_perm("manage_users")
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    old_role, old_active = target.role, target.is_active
    form = UserEditForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                if user.role != old_role:
                    _log(request, f"user {user.username}", f"role changed from {old_role} to {user.role}")
                if user.is_active != old_active:
                    _log(request, f"user {user.username}", "activated" if user.is_active else "deactivated")
                if not admin_remains():
                    raise LockoutError
        except LockoutError:
            messages.error(request, LockoutError.message)
            return redirect("user_edit", pk=pk)
        messages.success(request, f"User {target.username} saved.")
        return redirect("user_list")
    return render(request, "accounts/user_form.html", {"form": form, "title": f"Edit {target.username}", "target": target})


@require_perm("manage_users")
def user_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = PasswordResetForm(target, request.POST or None)
    if request.method == "POST" and form.is_valid():
        target.set_password(form.cleaned_data["password1"])
        target.failed_logins = 0
        target.locked_until = None
        target.save()
        if target == request.user:
            update_session_auth_hash(request, target)
        _log(request, f"user {target.username}", "password reset")
        messages.success(request, f"Password for {target.username} changed.")
        return redirect("user_list")
    return render(request, "accounts/user_form.html", {"form": form, "title": f"Reset password for {target.username}", "target": target})


# ---------------------------------------------------------------- roles


@require_perm("manage_roles")
def role_list(request):
    roles = Role.objects.prefetch_related("permissions", "users")
    return render(request, "accounts/role_list.html", {"roles": roles})


@require_perm("manage_roles")
def role_edit(request, pk=None):
    role = get_object_or_404(Role, pk=pk) if pk else None
    old_codes = role.permission_codes() if role else set()
    old_name = role.name if role else None
    form = RoleForm(request.POST or None, instance=role)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                saved = form.save()
                new_codes = saved.permission_codes()
                if role is None:
                    _log(request, f"role {saved.name}", "created with " + (", ".join(sorted(new_codes)) or "no permissions"))
                else:
                    if old_name != saved.name:
                        _log(request, f"role {saved.name}", f"renamed from {old_name}")
                    for code in sorted(new_codes - old_codes):
                        _log(request, f"role {saved.name}", f"added {code}")
                    for code in sorted(old_codes - new_codes):
                        _log(request, f"role {saved.name}", f"removed {code}")
                if not admin_remains():
                    raise LockoutError
        except LockoutError:
            messages.error(request, LockoutError.message)
            return redirect("role_edit", pk=pk) if pk else redirect("role_list")
        messages.success(request, f"Role {saved.name} saved.")
        return redirect("role_list")
    title = f"Role: {role.name}" if role else "New role"
    return render(request, "accounts/role_form.html", {"form": form, "title": title, "role": role})


@require_perm("manage_roles")
def permission_log(request):
    changes = PermissionChange.objects.select_related("changed_by")[:500]
    return render(request, "accounts/permission_log.html", {"changes": changes})
