from django.contrib import admin
from .models import DailyPlan, HourlyPlan, Model


@admin.register(DailyPlan)
class DailyPlanAdmin(admin.ModelAdmin):
    list_display = ("date", "work_center", "subprocess")
    list_filter  = ("work_center", "subprocess", "date")


@admin.register(HourlyPlan)
class HourlyPlanAdmin(admin.ModelAdmin):
    list_display = ("daily_plan", "hour", "planned_quantity")


@admin.register(Model)
class ModelAdmin(admin.ModelAdmin):
    list_display  = ("name",)
    search_fields = ("name",)