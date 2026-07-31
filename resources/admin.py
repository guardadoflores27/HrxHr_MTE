# resources/admin.py
# ─────────────────────────────────────────────────────────────────────────────
# Both models were previously invisible (unregistered). Now fully manageable.
# ─────────────────────────────────────────────────────────────────────────────

from django.contrib import admin

from .models import WindingMachine, MachineAssignment


@admin.register(WindingMachine)
class WindingMachineAdmin(admin.ModelAdmin):
    list_display  = ("name", "is_active", "assignment_count")
    list_filter   = ("is_active",)
    search_fields = ("name",)
    ordering      = ("name",)
    list_editable = ("is_active",)

    @admin.display(description="Assignments")
    def assignment_count(self, obj):
        return obj.machineassignment_set.count()

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("machineassignment_set")


@admin.register(MachineAssignment)
class MachineAssignmentAdmin(admin.ModelAdmin):
    list_display        = ("machine", "subprocess", "date")
    list_filter         = ("date", "machine")
    search_fields       = ("machine__name", "subprocess__name")
    date_hierarchy      = "date"
    autocomplete_fields = ("subprocess", "machine")
    list_select_related = ("machine", "subprocess")
    ordering            = ("-date",)
    list_per_page       = 50
