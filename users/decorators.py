# users/decorators.py
"""
Role-based access decorators.

Permission matrix (from spec):
┌──────────────────────┬────────┬──────────┬──────────┬───────┐
│ Section              │ Leader │ Operator │ Engineer │ Admin │
├──────────────────────┼────────┼──────────┼──────────┼───────┤
│ Dashboard            │ full   │ full     │ full     │ full  │
│ Daily Plans          │ full   │ view     │ view     │ full  │
│ Hourly Plans         │ full   │ view     │ view     │ full  │
│ Execution            │ full   │ view     │ view     │ full  │
│ Work Centers         │ view   │ view     │ full     │ full  │
│ Subprocesses         │ view   │ view     │ full     │ full  │
│ Models               │ full   │ view     │ view     │ full  │
│ Shifts               │ view*  │ view*    │ full     │ full  │
│ Users Administration │ view   │ view     │ view     │ full  │
└──────────────────────┴────────┴──────────┴──────────┴───────┘

* Leader & Operator: can VIEW shifts (used in Daily Plans) but
  the sidebar link is hidden from them and they cannot access
  the admin pages directly (decorator blocks them).
"""

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def _get_profile(request):
    user = request.user
    if not user.is_authenticated:
        return None
    return getattr(user, "profile", None)


def _deny(request, msg="You don't have permission to perform this action."):
    messages.error(request, msg)
    return redirect("planning:dashboard")


# ── generic helpers ───────────────────────────────────────────────────────────

def role_required(*roles):
    """Allow only users whose role is in `roles`."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            profile = _get_profile(request)
            if profile is None or profile.role not in roles:
                return _deny(request, "You don't have permission to access this section.")
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def admin_only(view_func):
    """Allow admin only."""
    return role_required("admin")(view_func)


def admin_or_leader(view_func):
    """Allow admin or leader."""
    return role_required("admin", "leader")(view_func)


def admin_or_engineer(view_func):
    """
    Allow admin or engineer.
    Used for: Work Centers, Subprocesses, and Shifts management.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        profile = _get_profile(request)
        if profile is None or profile.role not in ("admin", "engineer"):
            return _deny(
                request,
                "Only Admins and Engineers can access this section."
            )
        return view_func(request, *args, **kwargs)
    return _wrapped


def not_operator_write(view_func):
    """Block Operator & Engineer from write operations; Leader & Admin pass."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        profile = _get_profile(request)
        if profile and profile.role in ("operator", "engineer") and request.method == "POST":
            return _deny(request, "Your role does not allow creating or editing records.")
        return view_func(request, *args, **kwargs)
    return _wrapped


def engineer_or_admin_write(view_func):
    """Only Engineer & Admin can write in Work Centers / Subprocesses."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        profile = _get_profile(request)
        if profile and profile.role in ("leader", "operator") and request.method == "POST":
            return _deny(request, "Only Engineers and Admins can modify this section.")
        return view_func(request, *args, **kwargs)
    return _wrapped