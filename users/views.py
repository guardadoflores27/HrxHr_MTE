# users/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages

from .models import UserProfile
from .forms  import CreateUserForm, EditUserForm
from .decorators import admin_only


@login_required
def profile(request):
    return render(request, "users/profile.html")


# ── User list ─────────────────────────────────────────────────────────────────

@login_required
def user_list(request):
    """All roles can VIEW the user list (read-only)."""
    q    = request.GET.get("q",    "").strip()
    role = request.GET.get("role", "").strip()

    users = User.objects.select_related("profile").order_by("username")
    if q:
        users = users.filter(username__icontains=q) | \
                users.filter(first_name__icontains=q) | \
                users.filter(last_name__icontains=q)  | \
                users.filter(email__icontains=q)
    if role:
        users = users.filter(profile__role=role)

    return render(request, "users/user_list.html", {
        "users":        users,
        "role_choices": UserProfile.ROLE_CHOICES,
        "filter":       {"q": q, "role": role},
    })


# ── Create user (Admin only) ──────────────────────────────────────────────────

@login_required
@admin_only
def user_create(request):
    form = CreateUserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if form.generated_password:
            messages.success(
                request,
                f"User '{user.username}' created. Default password: {form.generated_password} "
                f"— share it with the employee now, it won't be shown again."
            )
        else:
            messages.success(request, f"User '{user.username}' created successfully.")
        return redirect("users:user_list")
    return render(request, "users/user_create.html", {"form": form})


# ── Edit user role (Admin only) ───────────────────────────────────────────────

@login_required
@admin_only
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)

    # Prevent editing yourself via this form
    if target == request.user:
        messages.warning(request, "You cannot edit your own account here.")
        return redirect("users:user_list")

    form = EditUserForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"User '{target.username}' updated.")
        return redirect("users:user_edit_list")
    return render(request, "users/user_edit.html", {"form": form, "target": target})


# ── Delete user (Admin only) ──────────────────────────────────────────────────

@login_required
@admin_only
def user_delete(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect("users:user_edit_list")
    if request.method == "POST":
        username = target.username
        target.delete()
        messages.success(request, f"User '{username}' has been deleted.")
        return redirect("users:user_edit_list")
    return render(request, "users/user_delete_confirm.html", {"target": target})


# ── Edit list (Admin only) ────────────────────────────────────────────────────

@login_required
@admin_only
def user_edit_list(request):
    q    = request.GET.get("q",    "").strip()
    role = request.GET.get("role", "").strip()

    users = User.objects.select_related("profile").order_by("username")
    if q:
        users = users.filter(username__icontains=q) | \
                users.filter(first_name__icontains=q) | \
                users.filter(last_name__icontains=q)
    if role:
        users = users.filter(profile__role=role)

    return render(request, "users/user_edit_list.html", {
        "users":        users,
        "role_choices": UserProfile.ROLE_CHOICES,
        "filter":       {"q": q, "role": role},
        "current_user": request.user,
    })
