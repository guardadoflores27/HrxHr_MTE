# analytics/urls.py
from django.urls import path
from . import views

app_name = "analytics"

urlpatterns = [
    path("",                      views.analytics_dashboard, name="dashboard"),
    path("day/",                  views.day_dashboard,       name="day_dashboard"),
    path("period/",               views.period_dashboard,    name="period_dashboard"),
    path("api/period/",           views.api_period_data,     name="api_period_data"),
    path("export/day/<str:fmt>/",    views.export_day,       name="export_day"),
    path("export/period/<str:fmt>/", views.export_period,    name="export_period"),
    path("api/day-chart/",       views.api_day_chart,       name="api_day_chart"),
    path("api/kpis/",             views.api_kpis,            name="api_kpis"),
    path("api/by/<str:dimension>/", views.api_by_dimension,  name="api_by_dimension"),
    path("api/over-time/",        views.api_over_time,       name="api_over_time"),
    path("api/pareto/",           views.api_pareto,          name="api_pareto"),
    path("api/planned-vs-actual/",views.api_planned_vs_actual, name="api_planned_vs_actual"),
    path("api/extended-kpis/",    views.api_extended_kpis,    name="api_extended_kpis"),
    path("api/performers/<str:kind>/", views.api_performers,  name="api_performers"),
    path("api/trend/<str:metric>/",    views.api_trend,       name="api_trend"),
]