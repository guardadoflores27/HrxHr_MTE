# planning/urls.py
# ─────────────────────────────────────────────────────────────────────────────
# COPY-PASTE → hrxhr_project/planning/urls.py
# ─────────────────────────────────────────────────────────────────────────────

from django.urls import path
from . import views

app_name = "planning"

urlpatterns = [

    # ── Dashboard ─────────────────────────────────────────────────────────────
    path("", views.dashboard, name="dashboard"),

    # ── Daily Plans ───────────────────────────────────────────────────────────
    path("plans/",                      views.daily_plan_list,   name="daily_plan_list"),
    path("plans/new/",                  views.daily_plan_create, name="daily_plan_create"),
    path("plans/<int:pk>/edit/",        views.daily_plan_update, name="daily_plan_update"),
    path("plans/<int:pk>/delete/",      views.daily_plan_delete, name="daily_plan_delete"),

    # ── Hourly Plan — main view + row delete ──────────────────────────────────
    path("plans/<int:plan_id>/hours/",
         views.hourly_plan_view,   name="hourly_plan"),
    path("plans/<int:plan_id>/hours/<int:hp_id>/delete/",
         views.hourly_plan_delete, name="hourly_delete"),

    # ── Hourly Plan — AJAX API endpoints ─────────────────────────────────────
    path("plans/<int:plan_id>/api/add-row/",
         views.api_add_row,          name="api_add_row"),
    path("plans/<int:plan_id>/api/edit-row/<int:hp_id>/",
         views.api_edit_row,         name="api_edit_row"),
    path("plans/<int:plan_id>/api/add-block/",
         views.api_add_block,         name="api_add_block"),
    path("plans/<int:plan_id>/api/edit-block/<int:block_id>/",
         views.api_edit_block,        name="api_edit_block"),
    path("plans/<int:plan_id>/api/remove-block/<int:block_id>/",
         views.api_remove_block,      name="api_remove_block"),
    path("plans/<int:plan_id>/api/update-headcount/",
         views.api_update_headcount,  name="api_update_headcount"),
    path("plans/<int:plan_id>/api/blocks/",
         views.api_get_blocks,        name="api_get_blocks"),

    # ── Hourly Plan Board ─────────────────────────────────────────────────────
    path("hours/", views.hourly_plan_board, name="hourly_plan_board"),

    # ── Model Catalog ─────────────────────────────────────────────────────────
    path("models/",                 views.model_list,   name="model_list"),
    path("models/<int:pk>/delete/", views.model_delete, name="model_delete"),

    # ── General AJAX ──────────────────────────────────────────────────────────
    path("api/subprocesses/",  views.subprocess_by_workcenter, name="subprocess_by_workcenter"),
    path("api/models/search/", views.api_model_search,         name="api_model_search"),
]