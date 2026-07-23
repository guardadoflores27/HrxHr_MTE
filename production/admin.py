# production/admin.py
from django.contrib import admin
from .models import (
    HourlyExecution, LossReason, ExecutionLossReason,
    EventCategory, EventType, ExecutionEvent,
)


@admin.register(LossReason)
class LossReasonAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(HourlyExecution)
class HourlyExecutionAdmin(admin.ModelAdmin):
    list_display = ("hourly_plan", "actual_quantity", "scrap_quantity")
    list_select_related = ("hourly_plan",)


@admin.register(ExecutionLossReason)
class ExecutionLossReasonAdmin(admin.ModelAdmin):
    list_display = ("execution", "loss_reason")
    list_filter = ("loss_reason",)
    list_select_related = ("execution", "loss_reason")


@admin.register(EventCategory)
class EventCategoryAdmin(admin.ModelAdmin):
    list_display  = ("name", "code", "is_planned", "is_active", "order")
    list_editable = ("is_planned", "is_active", "order")
    list_filter   = ("is_planned", "is_active")
    search_fields = ("name", "code")
    ordering      = ("order", "name")


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display  = ("name", "category", "icon", "color", "requires_comment",
                     "is_active", "order")
    list_editable = ("category", "icon", "color", "requires_comment",
                     "is_active", "order")
    list_filter   = ("category", "is_active", "requires_comment")
    search_fields = ("name",)
    ordering      = ("order", "name")
    list_select_related = ("category",)


@admin.register(ExecutionEvent)
class ExecutionEventAdmin(admin.ModelAdmin):
    list_display  = ("execution", "event_type", "duration_minutes", "source",
                     "created_by", "created_at")
    list_filter   = ("source", "event_type", "event_type__category")
    list_select_related = ("execution", "event_type", "event_type__category",
                           "created_by", "source_block")
    date_hierarchy = "created_at"
    readonly_fields = ("source", "source_block")