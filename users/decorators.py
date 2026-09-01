# users/decorators.py
"""
Role-based access decorators.

Permission matrix (supersedes the original 4-role spec; Supervisor is
a new role, equivalent to Leader but with full control over Shifts as well):

┌──────────────────────┬────────┬──────────┬──────────┬────────────┬───────┐
│ Section              │ Leader │ Operator │ Engineer │ Supervisor │ Admin │
├──────────────────────┼────────┼──────────┼──────────┼────────────┼───────┤
│ Dashboard            │ full   │ full     │ full     │ full       │ full  │
│ Daily Plans          │ full   │ view     │ view     │ full       │ full  │
│ Hourly Plans         │ full   │ view     │ view     │ full       │ full  │
│ Execution            │ full   │ view     │ view     │ full       │ full  │
│ Work Centers         │ view   │ view     │ full     │ view       │ full  │
│ Subprocesses         │ view   │ view     │ full     │ view       │ full  │
│ Models               │ full   │ view     │ view     │ full       │ full  │
│ Shifts               │ view*  │ view*    │ full     │ full       │ full  │
│ Users Administration │ view   │ view     │ view     │ view       │ full  │
└──────────────────────┴────────┴──────────┴──────────┴────────────┴───────┘

* Leader, Operator & Supervisor: can VIEW shifts (used in Daily Plans);
  for Leader/Operator the sidebar link to the Shifts admin screen is
  hidden and the admin pages themselves are blocked. Supervisor gets
  full access to the Shifts admin screen itself (see
  `admin_engineer_or_supervisor` below).
"""

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse


def _get_profile(request):
    user = request.user
    if not user.is_authenticated:
        return None
    return getattr(user, "profile", None)

def get_role(user):
    """
    SINGLE SOURCE OF TRUTH for "what is this user's role" — returns the role
    string (e.g. "admin") or None for anonymous users / users with no
    profile. Takes a User object (not a request) so it works the same from
    views (`get_role(request.user)`) and from plain service functions that
    only ever see a user.
    
    This used to be reimplemented separately in core/views.py::_role,
    planning/views.py::_role, and planning/services.py::get_user_role — three
    copies of the same getattr(user, "profile", None) check that all had to
    be edited in lockstep every time a role changed (that's exactly how the
    Engineer/Hourly-Plans bug happened). Those three now delegate here.
    """
    profile = getattr(user, "profile", None)
    return profile.role if profile else None


# SINGLE SOURCE OF TRUTH for the permission matrix documented above — same
# rows/columns as the docstring table. This is what users.views.profile
# passes to templates/users/profile.html for the "Your Permissions" panel,
# so that panel can never drift out of sync with the table above again.
PERMISSION_MATRIX = [
    # (section,                leader,  operator, engineer, supervisor, admin)
    ("Dashboard",              "full",  "full",   "full",   "full",     "full"),
    ("Daily Plans",            "full",  "view",   "view",   "full",     "full"),
    ("Hourly Plans",           "full",  "view",   "view",   "full",     "full"),
    ("Execution",              "full",  "view",   "view",   "full",     "full"),
    ("Work Centers",           "view",  "view",   "full",   "view",     "full"),
    ("Subprocesses",           "view",  "view",   "full",   "view",     "full"),
    ("Models",                 "full",  "view",   "view",   "full",     "full"),
    ("Shifts",                 "view",  "view",   "full",   "full",     "full"),
    ("Users Administration",   "view",  "view",   "view",   "view",     "full"),
]


def _deny(request, msg="You don't have permission to perform this action."):
    # AJAX callers (e.g. Execution's fetch-based save) need a JSON error,
    # not a redirect — a redirect response breaks their response parsing.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": msg}, status=403)
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


def admin_engineer_or_supervisor(view_func):
    """
    Allow admin, engineer, or supervisor.
    Used for: Shift management only (Work Centers/Subprocesses stay
    admin_or_engineer — Supervisor has view-only there, per the matrix).
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        profile = _get_profile(request)
        if profile is None or profile.role not in ("admin", "engineer", "supervisor"):
            return _deny(
                request,
                "Only Admins, Engineers, and Supervisors can access this section."
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