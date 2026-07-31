# production/admin.py
# ─────────────────────────────────────────────────────────────────────────────
# Groups the five situational comment fields into a readable fieldset, exposes
# computed efficiency/diff as read-only columns, and inlines loss reasons.
# ─────────────────────────────────────────────────────────────────────────────

from django.contrib import admin

from .models import HourlyExecution, LossReason, ExecutionLossReason


class ExecutionLossReasonInline(admin.TabularInline):
    model = ExecutionLossReason
    extra = 0
    autocomplete_fields = ("loss_reason",)


@admin.register(LossReason)
class LossReasonAdmin(admin.ModelAdmin):
    list_display  = ("name", "is_default")
    list_filter   = ("is_default",)
    search_fields = ("name",)
    ordering      = ("name",)
    list_editable = ("is_default",)


@admin.register(HourlyExecution)
class HourlyExecutionAdmin(admin.ModelAdmin):
    list_display        = ("hourly_plan", "actual_quantity", "scrap_quantity",
                           "diff_display", "efficiency_display")
    list_filter         = ("hourly_plan__daily_plan__work_center",
                           "hourly_plan__daily_plan__date",
                           "hourly_plan__is_overtime")
    search_fields       = ("hourly_plan__model__name",
                           "hourly_plan__daily_plan__subprocess__name")
    autocomplete_fields = ("hourly_plan",)
    list_select_related = ("hourly_plan", "hourly_plan__model",
                           "hourly_plan__daily_plan")
    inlines             = (ExecutionLossReasonInline,)
    list_per_page       = 50
    fieldsets = (
        ("Plan link",  {"fields": ("hourly_plan",)}),
        ("Quantities", {"fields": ("actual_quantity", "scrap_quantity")}),
        ("Situational comments", {
            "fields": ("comments", "scrap_comments", "over_comments",
                       "ok_comments", "zero_comment"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Diff")
    def diff_display(self, obj):
        return obj.diff_quantity

    @admin.display(description="EFF %")
    def efficiency_display(self, obj):
        pct = obj.efficiency_pct
        return "—" if pct is None else f"{pct}%"


@admin.register(ExecutionLossReason)
class ExecutionLossReasonAdmin(admin.ModelAdmin):
    list_display        = ("execution", "loss_reason")
    list_filter         = ("loss_reason",)
    search_fields       = ("loss_reason__name",)
    autocomplete_fields = ("execution", "loss_reason")
    list_select_related = ("execution", "loss_reason")
    list_per_page       = 50
