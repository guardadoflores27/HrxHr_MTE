# production/services.py
# hrxhr_project/production/services.py
#
# Reporting helpers for Operational Events. Every function here reads
# structured ExecutionEvent rows only — no comment parsing anywhere. These
# are the building blocks for the KPI cards, Pareto chart, and dashboards
# described in the Operational Events spec.

from django.db.models import Sum, Count, F
from .models import ExecutionEvent


def _base_queryset(date_from=None, date_to=None, work_center_id=None,
                    shift_id=None, model_id=None, supervisor_id=None):
    """Common filterable base queryset joined to plan/execution context."""
    qs = ExecutionEvent.objects.select_related(
        "event_type", "execution", "execution__hourly_plan",
        "execution__hourly_plan__daily_plan",
        "execution__hourly_plan__daily_plan__work_center",
        "execution__hourly_plan__daily_plan__shift",
        "execution__hourly_plan__model",
    )
    if date_from:
        qs = qs.filter(execution__hourly_plan__daily_plan__date__gte=date_from)
    if date_to:
        qs = qs.filter(execution__hourly_plan__daily_plan__date__lte=date_to)
    if work_center_id:
        qs = qs.filter(execution__hourly_plan__daily_plan__work_center_id=work_center_id)
    if shift_id:
        qs = qs.filter(execution__hourly_plan__daily_plan__shift_id=shift_id)
    if model_id:
        qs = qs.filter(execution__hourly_plan__model_id=model_id)
    return qs


def total_minutes_by_event_type(**filters):
    """Total minutes per EventType — feeds 'Operational Events Summary' and
    the Pareto chart."""
    qs = _base_queryset(**filters)
    return list(
        qs.values("event_type__id", "event_type__name", "event_type__icon",
                  "event_type__color")
          .annotate(total_minutes=Sum("duration_minutes"), event_count=Count("id"))
          .order_by("-total_minutes")
    )


def total_minutes_by_shift(**filters):
    """Total minutes per Shift — e.g. Total Lunch por turno."""
    qs = _base_queryset(**filters)
    return list(
        qs.values("execution__hourly_plan__daily_plan__shift__id",
                  "execution__hourly_plan__daily_plan__shift__name")
          .annotate(total_minutes=Sum("duration_minutes"))
          .order_by("-total_minutes")
    )


def total_minutes_by_model(**filters):
    """Distribución de eventos por modelo."""
    qs = _base_queryset(**filters)
    return list(
        qs.values("execution__hourly_plan__model__id",
                  "execution__hourly_plan__model__name")
          .annotate(total_minutes=Sum("duration_minutes"))
          .order_by("-total_minutes")
    )


def total_minutes_by_work_center(**filters):
    """Distribución por Work Center."""
    qs = _base_queryset(**filters)
    return list(
        qs.values("execution__hourly_plan__daily_plan__work_center__id",
                  "execution__hourly_plan__daily_plan__work_center__name")
          .annotate(total_minutes=Sum("duration_minutes"))
          .order_by("-total_minutes")
    )


def daily_non_productive_minutes(**filters):
    """Tiempo total no productivo por día."""
    qs = _base_queryset(**filters)
    return list(
        qs.values("execution__hourly_plan__daily_plan__date")
          .annotate(total_minutes=Sum("duration_minutes"))
          .order_by("execution__hourly_plan__daily_plan__date")
    )


def pareto_by_event_type(**filters):
    """Event types ranked by share of total non-productive minutes, with a
    running cumulative percentage — feeds the Pareto chart."""
    rows  = total_minutes_by_event_type(**filters)
    total = sum(r["total_minutes"] or 0 for r in rows) or 1
    cumulative = 0
    for r in rows:
        pct = round((r["total_minutes"] or 0) / total * 100, 1)
        cumulative += pct
        r["pct"] = pct
        r["cumulative_pct"] = round(cumulative, 1)
    return rows


def productive_vs_non_productive_pct(planned_actual_seconds_total=None, **filters):
    """Non-productive-time KPI: (event minutes) / (available shift minutes).
    `planned_actual_seconds_total` lets the caller pass the total scheduled
    minutes for the same filtered window; falls back to None when unknown so
    callers can decide how to render 'N/A'."""
    qs = _base_queryset(**filters)
    non_productive_minutes = qs.aggregate(t=Sum("duration_minutes"))["t"] or 0
    if not planned_actual_seconds_total:
        return {"non_productive_minutes": non_productive_minutes,
                "productive_pct": None, "non_productive_pct": None}
    non_prod_pct = round(non_productive_minutes / planned_actual_seconds_total * 100, 1)
    return {
        "non_productive_minutes": non_productive_minutes,
        "non_productive_pct":     non_prod_pct,
        "productive_pct":         round(100 - non_prod_pct, 1),
    }
