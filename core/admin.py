# core/admin.py
# ─────────────────────────────────────────────────────────────────────────────
# Registers every core catalog model with full list/search/filter config,
# inlines, and read-only audit fields. Previously SubProcessType and Shift
# were NOT registered at all — they are now fully manageable.
# ─────────────────────────────────────────────────────────────────────────────

from django.contrib import admin

from .models import WorkCenter, SubProcess, SubProcessType, Shift


# ─── Shared audit config ──────────────────────────────────────────────────────
# AuditMixin fields should never be edited by hand — show them, lock them.
AUDIT_READONLY = ("created_by", "updated_by", "created_at", "updated_at")


class SubProcessInline(admin.TabularInline):
    """Edit a work center's subprocesses inline on the WorkCenter page."""
    model = SubProcess
    extra = 0
    fields = ("name", "subprocess_type")
    autocomplete_fields = ("subprocess_type",)
    show_change_link = True


@admin.register(WorkCenter)
class WorkCenterAdmin(admin.ModelAdmin):
    list_display   = ("name", "is_active", "subprocess_count", "created_at")
    list_filter    = ("is_active", "created_at")
    search_fields  = ("name", "description")
    ordering       = ("name",)
    readonly_fields = AUDIT_READONLY
    inlines        = (SubProcessInline,)
    list_per_page  = 50
    fieldsets = (
        (None,        {"fields": ("name", "description", "is_active")}),
        ("Audit",     {"fields": AUDIT_READONLY, "classes": ("collapse",)}),
    )

    @admin.display(description="Subprocesses")
    def subprocess_count(self, obj):
        return obj.subprocess_set.count()

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("subprocess_set")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SubProcess)
class SubProcessAdmin(admin.ModelAdmin):
    list_display        = ("name", "work_center", "subprocess_type", "conversion_label")
    list_filter         = ("work_center", "subprocess_type", "subprocess_type__applies_to")
    search_fields       = ("name", "work_center__name", "subprocess_type__name")
    ordering            = ("work_center__name", "name")
    autocomplete_fields = ("work_center", "subprocess_type")
    list_select_related = ("work_center", "subprocess_type")
    readonly_fields     = AUDIT_READONLY
    list_per_page       = 50
    fieldsets = (
        (None,    {"fields": ("work_center", "name", "subprocess_type")}),
        ("Audit", {"fields": AUDIT_READONLY, "classes": ("collapse",)}),
    )

    @admin.display(description="Conversion")
    def conversion_label(self, obj):
        return obj.conversion_label

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SubProcessType)
class SubProcessTypeAdmin(admin.ModelAdmin):
    list_display   = ("name", "applies_to", "units_per_piece",
                      "conversion_label", "is_active", "subprocess_count")
    list_filter    = ("applies_to", "is_active")
    search_fields  = ("name",)
    ordering       = ("name",)
    list_editable  = ("is_active",)
    list_per_page  = 50

    @admin.display(description="Conversion")
    def conversion_label(self, obj):
        return obj.conversion_label

    @admin.display(description="Used by")
    def subprocess_count(self, obj):
        return obj.subprocesses.count()

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("subprocesses")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display   = ("name", "code", "duration_display", "days_label",
                      "crosses_midnight", "is_active")
    list_filter    = ("is_active",)
    search_fields  = ("name", "code")
    ordering       = ("start_time", "name")
    list_editable  = ("is_active",)
    list_per_page  = 50
    fieldsets = (
        (None,        {"fields": ("name", "code", "is_active")}),
        ("Schedule",  {"fields": ("start_time", "end_time", "days_of_week")}),
    )

    @admin.display(description="Duration")
    def duration_display(self, obj):
        return obj.duration_display

    @admin.display(description="Days", boolean=False)
    def days_label(self, obj):
        return ", ".join(obj.days_display) or "—"

    @admin.display(description="Crosses midnight", boolean=True)
    def crosses_midnight(self, obj):
        return obj.crosses_midnight
