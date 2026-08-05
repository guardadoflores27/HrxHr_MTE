# planning/admin.py
# ─────────────────────────────────────────────────────────────────────────────
# Full admin config for the planning domain. Adds:
#   • HourlyPlan + HourlyPlanBlock inlines on DailyPlan (edit a plan on one page)
#   • HeadcountAudit registered READ-ONLY (audit records must not be hand-edited)
#   • CSV export action for DailyPlan
# ─────────────────────────────────────────────────────────────────────────────

import csv
from django.contrib import admin
from django.http import HttpResponse

from .models import (
    Model, DailyPlan, HourlyPlan, HourlyPlanBlock, HeadcountAudit,
)


# ─── Reusable CSV export action ───────────────────────────────────────────────

@admin.action(description="Export selected to CSV")
def export_as_csv(modeladmin, request, queryset):
    meta   = modeladmin.model._meta
    fields = [f.name for f in meta.fields]
    resp   = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f"attachment; filename={meta.verbose_name_plural}.csv"
    writer = csv.writer(resp)
    writer.writerow(fields)
    for obj in queryset:
        writer.writerow([getattr(obj, f) for f in fields])
    return resp


# ─── Inlines ──────────────────────────────────────────────────────────────────

class HourlyPlanInline(admin.TabularInline):
    model = HourlyPlan
    extra = 0
    fields = ("hour", "model", "planned_quantity", "headcount", "is_overtime")
    autocomplete_fields = ("model",)
    ordering = ("hour",)
    show_change_link = True


class HourlyPlanBlockInline(admin.TabularInline):
    model = HourlyPlanBlock
    extra = 0
    fields = ("slot_time", "block_type", "minutes", "reason", "created_by", "created_at")
    readonly_fields = ("created_by", "created_at")
    ordering = ("slot_time",)


# ─── Model catalog ────────────────────────────────────────────────────────────

@admin.register(Model)
class ProductModelAdmin(admin.ModelAdmin):
    list_display  = ("name", "hourly_plan_count")
    search_fields = ("name",)
    ordering      = ("name",)
    list_per_page = 100

    @admin.display(description="Used in hourly plans")
    def hourly_plan_count(self, obj):
        return obj.hourlyplan_set.count()

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("hourlyplan_set")


# ─── Daily plan (with inlines) ────────────────────────────────────────────────

@admin.register(DailyPlan)
class DailyPlanAdmin(admin.ModelAdmin):
    list_display        = ("date", "work_center", "subprocess", "shift",
                           "headcount", "creator_display")
    list_filter         = ("work_center", "shift", "subprocess", "date")
    search_fields       = ("work_center__name", "subprocess__name", "shift__name")
    date_hierarchy      = "date"
    ordering            = ("-date",)
    autocomplete_fields = ("work_center", "subprocess", "shift")
    list_select_related = ("work_center", "subprocess", "shift", "created_by")
    readonly_fields     = ("created_by", "created_by_name", "created_at",
                           "updated_by", "updated_by_name", "updated_at")
    inlines             = (HourlyPlanInline, HourlyPlanBlockInline)
    actions             = (export_as_csv,)
    list_per_page       = 50
    fieldsets = (
        (None,    {"fields": ("date", "work_center", "subprocess", "shift", "headcount")}),
        ("Audit", {"fields": readonly_fields, "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by, obj.created_by_name = request.user, request.user.username
        obj.updated_by, obj.updated_by_name = request.user, request.user.username
        super().save_model(request, obj, form, change)


@admin.register(HourlyPlan)
class HourlyPlanAdmin(admin.ModelAdmin):
    list_display        = ("daily_plan", "hour", "model", "planned_quantity",
                           "headcount", "is_overtime")
    list_filter         = ("is_overtime", "daily_plan__work_center", "daily_plan__date")
    search_fields       = ("model__name", "daily_plan__subprocess__name")
    autocomplete_fields = ("daily_plan", "model")
    list_select_related = ("daily_plan", "model", "daily_plan__subprocess")
    ordering            = ("-daily_plan__date", "hour")
    list_per_page       = 50


# ─── Audit records — READ ONLY ────────────────────────────────────────────────

@admin.register(HourlyPlanBlock)
class HourlyPlanBlockAdmin(admin.ModelAdmin):
    list_display        = ("daily_plan", "slot_time", "block_type", "minutes",
                           "reason", "created_by", "created_at")
    list_filter         = ("block_type", "created_at")
    search_fields       = ("daily_plan__subprocess__name", "reason")
    list_select_related = ("daily_plan", "created_by")
    ordering            = ("-created_at",)
    list_per_page       = 50

    def has_add_permission(self, request):        return False
    def has_change_permission(self, request, obj=None): return False


@admin.register(HeadcountAudit)
class HeadcountAuditAdmin(admin.ModelAdmin):
    list_display        = ("daily_plan", "previous_value", "new_value",
                           "modified_by_name", "modified_at")
    list_filter         = ("modified_at",)
    search_fields       = ("daily_plan__subprocess__name", "modified_by_name", "comment")
    list_select_related = ("daily_plan", "modified_by")
    ordering            = ("-modified_at",)
    list_per_page       = 50

    def has_add_permission(self, request):        return False
    def has_change_permission(self, request, obj=None): return False
