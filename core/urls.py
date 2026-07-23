# core/urls.py
# ─────────────────────────────────────────────────────────────────────────────
# COPY-PASTE → hrxhr_project/core/urls.py
# ─────────────────────────────────────────────────────────────────────────────

from django.urls import path
from . import views

app_name = "core"

urlpatterns = [

    # ── Work Centers ──────────────────────────────────────────────────────────
    path("workcenters/",                 views.wc_list,   name="wc_list"),
    path("workcenters/new/",             views.wc_create, name="wc_create"),
    path("workcenters/<int:pk>/edit/",   views.wc_update, name="wc_update"),
    path("workcenters/<int:pk>/delete/", views.wc_delete, name="wc_delete"),

    # ── Subprocess Types (Admin only) ─────────────────────────────────────────
    path("subprocess-types/",                 views.spt_list,   name="spt_list"),
    path("subprocess-types/new/",             views.spt_create, name="spt_create"),
    path("subprocess-types/<int:pk>/edit/",   views.spt_update, name="spt_update"),
    path("subprocess-types/<int:pk>/delete/", views.spt_delete, name="spt_delete"),

    # ── SubProcesses ──────────────────────────────────────────────────────────
    path("subprocesses/",                 views.sp_list,   name="sp_list"),
    path("subprocesses/new/",             views.sp_create, name="sp_create"),
    path("subprocesses/<int:pk>/edit/",   views.sp_update, name="sp_update"),
    path("subprocesses/<int:pk>/delete/", views.sp_delete, name="sp_delete"),

    # ── Shifts ────────────────────────────────────────────────────────────────
    path("shifts/",                       views.shift_list,   name="shift_list"),
    path("shifts/new/",                   views.shift_create, name="shift_create"),
    path("shifts/<int:pk>/edit/",         views.shift_update, name="shift_update"),
    path("shifts/<int:pk>/delete/",       views.shift_delete, name="shift_delete"),
]