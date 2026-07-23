# analytics/services.py
# ─────────────────────────────────────────────────────────────────────────────
# Dashboard KPI service layer.
#
# Every metric the spec asks for is computed here as a DB-side aggregation over
# normalized rows (no comment parsing, no Python loops over large querysets).
# Views/APIs call these functions and render the result; they contain no
# business logic themselves. This is the single place to add or change a KPI.
#
# Two fact sources:
#   • ExecutionEvent  — one row per operational event (downtime bucket).
#   • HourlyExecution — one row per (hour, model) with planned/actual quantities.
#
# All functions accept the same keyword filters and are safe to call with none.
# ─────────────────────────────────────────────────────────────────────────────

from django.db.models import Sum, Count, Avg, F, Q, IntegerField
from django.db.models.functions import (
    TruncDay, TruncWeek, TruncMonth, TruncYear,
)

from production.models import ExecutionEvent, HourlyExecution


# ─── Filterable base querysets ───────────────────────────────────────────────

_EVENT_PLAN = "execution__hourly_plan"
_EVENT_DAILY = f"{_EVENT_PLAN}__daily_plan"


def events_qs(date_from=None, date_to=None, work_center_id=None,
              subprocess_id=None, shift_id=None, model_id=None,
              operator_id=None, category_id=None, event_type_id=None):
    """Filtered ExecutionEvent queryset with all reporting joins preloaded."""
    qs = ExecutionEvent.objects.select_related(
        "event_type", "event_type__category", "execution",
        f"{_EVENT_PLAN}", f"{_EVENT_DAILY}",
        f"{_EVENT_DAILY}__work_center", f"{_EVENT_DAILY}__shift",
        f"{_EVENT_DAILY}__operator", f"{_EVENT_PLAN}__model",
        f"{_EVENT_PLAN}__operator",
    )
    if date_from:       qs = qs.filter(**{f"{_EVENT_DAILY}__date__gte": date_from})
    if date_to:         qs = qs.filter(**{f"{_EVENT_DAILY}__date__lte": date_to})
    if work_center_id:  qs = qs.filter(**{f"{_EVENT_DAILY}__work_center_id": work_center_id})
    if subprocess_id:   qs = qs.filter(**{f"{_EVENT_DAILY}__subprocess_id": subprocess_id})
    if shift_id:        qs = qs.filter(**{f"{_EVENT_DAILY}__shift_id": shift_id})
    if model_id:        qs = qs.filter(**{f"{_EVENT_PLAN}__model_id": model_id})
    if operator_id:     qs = qs.filter(**{f"{_EVENT_DAILY}__operator_id": operator_id})
    if category_id:     qs = qs.filter(event_type__category_id=category_id)
    if event_type_id:   qs = qs.filter(event_type_id=event_type_id)
    return qs


def executions_qs(date_from=None, date_to=None, work_center_id=None,
                  subprocess_id=None, shift_id=None, model_id=None,
                  operator_id=None, **_ignored):
    """Filtered HourlyExecution queryset (for production/plan-achievement KPIs)."""
    qs = HourlyExecution.objects.select_related(
        "hourly_plan", "hourly_plan__daily_plan",
        "hourly_plan__daily_plan__work_center",
        "hourly_plan__daily_plan__shift", "hourly_plan__model",
        "hourly_plan__daily_plan__subprocess",
    )
    dp = "hourly_plan__daily_plan"
    if date_from:      qs = qs.filter(**{f"{dp}__date__gte": date_from})
    if date_to:        qs = qs.filter(**{f"{dp}__date__lte": date_to})
    if work_center_id: qs = qs.filter(**{f"{dp}__work_center_id": work_center_id})
    if subprocess_id:  qs = qs.filter(**{f"{dp}__subprocess_id": subprocess_id})
    if shift_id:       qs = qs.filter(**{f"{dp}__shift_id": shift_id})
    if model_id:       qs = qs.filter(hourly_plan__model_id=model_id)
    if operator_id:    qs = qs.filter(**{f"{dp}__operator_id": operator_id})
    return qs


# ─── Time buckets (downtime / planned / unplanned / runtime) ─────────────────

def downtime_minutes(**f):
    """Total operational-event minutes (all downtime)."""
    return events_qs(**f).aggregate(t=Sum("duration_minutes"))["t"] or 0


def planned_downtime_minutes(**f):
    """Downtime whose category is flagged is_planned (lunch, prep, …)."""
    return (events_qs(**f)
            .filter(event_type__category__is_planned=True)
            .aggregate(t=Sum("duration_minutes"))["t"] or 0)


def unplanned_downtime_minutes(**f):
    """Downtime whose category is NOT planned (breakdowns, waiting, …)."""
    return (events_qs(**f)
            .filter(Q(event_type__category__is_planned=False)
                    | Q(event_type__category__isnull=True))
            .aggregate(t=Sum("duration_minutes"))["t"] or 0)


def scheduled_minutes(**f):
    """Scheduled/available minutes = 60 per captured hour row in scope.
    (Each HourlyPlan hour is a 60-minute slot.)"""
    return (executions_qs(**f).count()) * 60


def runtime_minutes(**f):
    """Runtime = scheduled minutes minus all downtime (floored at 0)."""
    return max(0, scheduled_minutes(**f) - downtime_minutes(**f))


def production_time_minutes(**f):
    """Alias for runtime — time actually spent producing."""
    return runtime_minutes(**f)


# ─── Availability / Utilization ──────────────────────────────────────────────

def availability_pct(**f):
    """Availability = runtime / (scheduled − planned downtime) × 100.
    Planned stops don't count against availability (standard OEE convention)."""
    sched   = scheduled_minutes(**f)
    planned = planned_downtime_minutes(**f)
    denom   = sched - planned
    if denom <= 0:
        return None
    return round(runtime_minutes(**f) / denom * 100, 1)


def utilization_pct(**f):
    """Utilization = runtime / scheduled × 100 (planned stops DO count)."""
    sched = scheduled_minutes(**f)
    if sched <= 0:
        return None
    return round(runtime_minutes(**f) / sched * 100, 1)


# ─── Event counts & averages ─────────────────────────────────────────────────

def number_of_events(**f):
    return events_qs(**f).count()


def average_duration_per_event(**f):
    return round(events_qs(**f).aggregate(a=Avg("duration_minutes"))["a"] or 0, 1)


# ─── "Group by dimension" helpers (events + minutes) ─────────────────────────

def _group(field_id, field_label, **f):
    return list(
        events_qs(**f)
        .values(field_id, field_label)
        .annotate(total_minutes=Sum("duration_minutes"), event_count=Count("id"))
        .order_by("-total_minutes")
    )


def by_category(**f):
    return _group("event_type__category__id", "event_type__category__name", **f)

def by_event_type(**f):
    return _group("event_type__id", "event_type__name", **f)

def by_shift(**f):
    return _group(f"{_EVENT_DAILY}__shift__id", f"{_EVENT_DAILY}__shift__name", **f)

def by_operator(**f):
    return _group(f"{_EVENT_DAILY}__operator__id",
                  f"{_EVENT_DAILY}__operator__username", **f)

def by_work_center(**f):
    return _group(f"{_EVENT_DAILY}__work_center__id",
                  f"{_EVENT_DAILY}__work_center__name", **f)

def by_model(**f):
    return _group(f"{_EVENT_PLAN}__model__id", f"{_EVENT_PLAN}__model__name", **f)


# ─── Time series (day / week / month / year) ─────────────────────────────────

_TRUNCS = {"day": TruncDay, "week": TruncWeek,
           "month": TruncMonth, "year": TruncYear}


def events_over_time(period="day", **f):
    """Total minutes and event count per period. `period` ∈ day/week/month/year."""
    trunc = _TRUNCS.get(period, TruncDay)
    date_field = f"{_EVENT_DAILY}__date"
    return list(
        events_qs(**f)
        .annotate(bucket=trunc(date_field))
        .values("bucket")
        .annotate(total_minutes=Sum("duration_minutes"), event_count=Count("id"))
        .order_by("bucket")
    )


# ─── Pareto (80/20 of downtime by category) ──────────────────────────────────

def pareto_by_category(**f):
    rows  = by_category(**f)
    total = sum(r["total_minutes"] or 0 for r in rows) or 1
    cum = 0
    for r in rows:
        pct = round((r["total_minutes"] or 0) / total * 100, 1)
        cum += pct
        r["pct"] = pct
        r["cumulative_pct"] = round(cum, 1)
    return rows


# ─── Planned vs Actual production & plan achievement ─────────────────────────

def planned_vs_actual(**f):
    """Totals of planned and actual production for the filtered window."""
    agg = executions_qs(**f).aggregate(
        planned=Sum("hourly_plan__planned_quantity"),
        actual=Sum("actual_quantity"),
        scrap=Sum("scrap_quantity"),
    )
    return {
        "planned": agg["planned"] or 0,
        "actual":  agg["actual"] or 0,
        "scrap":   agg["scrap"] or 0,
    }


def plan_achievement_pct(**f):
    """Plan Achievement % = actual / planned × 100 over the window."""
    pva = planned_vs_actual(**f)
    if pva["planned"] <= 0:
        return None
    return round(pva["actual"] / pva["planned"] * 100, 1)


def plan_achieved_hours(**f):
    """Count of hours where actual met or exceeded planned (planned > 0)."""
    return (executions_qs(**f)
            .filter(hourly_plan__planned_quantity__gt=0,
                    actual_quantity__gte=F("hourly_plan__planned_quantity"))
            .count())


# ─── One-call KPI bundle for the dashboard ───────────────────────────────────

def kpi_summary(**f):
    """Every headline KPI in a single dict — feeds the KPI cards."""
    pva = planned_vs_actual(**f)
    return {
        "downtime_minutes":          downtime_minutes(**f),
        "planned_downtime_minutes":  planned_downtime_minutes(**f),
        "unplanned_downtime_minutes":unplanned_downtime_minutes(**f),
        "runtime_minutes":           runtime_minutes(**f),
        "production_time_minutes":   production_time_minutes(**f),
        "scheduled_minutes":         scheduled_minutes(**f),
        "availability_pct":          availability_pct(**f),
        "utilization_pct":           utilization_pct(**f),
        "number_of_events":          number_of_events(**f),
        "average_duration_per_event":average_duration_per_event(**f),
        "planned_quantity":          pva["planned"],
        "actual_quantity":           pva["actual"],
        "scrap_quantity":            pva["scrap"],
        "plan_achievement_pct":      plan_achievement_pct(**f),
        "plan_achieved_hours":       plan_achieved_hours(**f),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 — Extended Analytics KPIs
# Productivity, Standard/Cycle time, Top/Bottom performers, trends, HC util.
# All piece-aware: quantities are stored in UNITS; pieces = units / factor
# (factor from the subprocess type). Reuses executions_qs / events_qs.
# ═══════════════════════════════════════════════════════════════════════════

from collections import defaultdict
import datetime as dt


def _factor_for_execution(ex):
    """Units-per-piece for an execution's subprocess (defaults to 1)."""
    sp = ex.hourly_plan.daily_plan.subprocess
    if sp and sp.subprocess_type_id:
        return sp.subprocess_type.units_per_piece or 1
    return 1


def _pieces(units, factor):
    if not factor or factor <= 0:
        factor = 1
    return round(units / factor, 2)


# ── Production efficiency & headcount utilization ────────────────────────────

def production_efficiency_pct(**f):
    """Production efficiency = actual units / planned units × 100 over scope."""
    pva = planned_vs_actual(**f)
    if pva["planned"] <= 0:
        return None
    return round(pva["actual"] / pva["planned"] * 100, 1)


def headcount_utilization(**f):
    """Rough head-count utilization: actual pieces produced per head, per hour.
    Returns pieces/head/hour so it is comparable across plans of different HC."""
    qs = executions_qs(**f).select_related(
        "hourly_plan", "hourly_plan__daily_plan",
        "hourly_plan__daily_plan__subprocess",
        "hourly_plan__daily_plan__subprocess__subprocess_type")
    total_pieces = 0.0
    total_head_hours = 0
    for ex in qs:
        factor = _factor_for_execution(ex)
        total_pieces += _pieces(ex.actual_quantity, factor)
        total_head_hours += ex.hourly_plan.effective_headcount()  # 1 hour each
    if total_head_hours <= 0:
        return None
    return round(total_pieces / total_head_hours, 2)


# ── Standard time (min/piece) & production rate (pieces/hour) ─────────────────

def standard_time_and_rate(**f):
    """Average Standard Time (minutes per piece) and Production Rate
    (pieces per hour) across the scope. One captured hour = 60 working minutes.

    Standard Time = total working minutes / total pieces produced.
    Production Rate = total pieces / total working hours.
    """
    qs = executions_qs(**f).select_related(
        "hourly_plan", "hourly_plan__daily_plan",
        "hourly_plan__daily_plan__subprocess",
        "hourly_plan__daily_plan__subprocess__subprocess_type")
    total_pieces = 0.0
    total_hours  = 0
    for ex in qs:
        if ex.actual_quantity <= 0:
            continue
        factor = _factor_for_execution(ex)
        total_pieces += _pieces(ex.actual_quantity, factor)
        total_hours  += 1               # each execution covers one hour
    if total_pieces <= 0:
        return {"standard_time_min_per_piece": None,
                "production_rate_pieces_per_hour": None,
                "cycle_time_min_per_piece": None}
    working_minutes = total_hours * 60
    std = round(working_minutes / total_pieces, 2)
    return {
        "standard_time_min_per_piece": std,
        # With no idle/setup split available, cycle time mirrors standard time.
        "cycle_time_min_per_piece": std,
        "production_rate_pieces_per_hour": round(total_pieces / total_hours, 2)
                                            if total_hours else None,
    }


# ── Productivity ranking by Work Center / Model (pieces) ─────────────────────

def _productivity_rows(group_key, **f):
    """Aggregate planned/actual (units + pieces) and productivity % grouped by
    `group_key` ∈ {'work_center', 'model'}. Sorted by piece productivity desc.
    """
    qs = executions_qs(**f).select_related(
        "hourly_plan", "hourly_plan__model", "hourly_plan__daily_plan",
        "hourly_plan__daily_plan__work_center",
        "hourly_plan__daily_plan__subprocess",
        "hourly_plan__daily_plan__subprocess__subprocess_type")

    acc = defaultdict(lambda: {"planned_u": 0, "actual_u": 0,
                               "planned_p": 0.0, "actual_p": 0.0})
    for ex in qs:
        hp = ex.hourly_plan
        if group_key == "work_center":
            key = hp.daily_plan.work_center.name
        else:
            key = hp.model.name
        factor = _factor_for_execution(ex)
        a = acc[key]
        a["planned_u"] += hp.planned_quantity
        a["actual_u"]  += ex.actual_quantity
        a["planned_p"] += _pieces(hp.planned_quantity, factor)
        a["actual_p"]  += _pieces(ex.actual_quantity, factor)

    rows = []
    for name, a in acc.items():
        prod = round(a["actual_p"] / a["planned_p"] * 100, 1) if a["planned_p"] else None
        rows.append({
            "name": name,
            "planned_units": a["planned_u"], "actual_units": a["actual_u"],
            "planned_pieces": round(a["planned_p"], 2),
            "actual_pieces": round(a["actual_p"], 2),
            "productivity_pct": prod,
        })
    # Sort by piece productivity desc; None (no plan) sinks to the bottom.
    rows.sort(key=lambda r: (r["productivity_pct"] is not None,
                             r["productivity_pct"] or 0), reverse=True)
    return rows


def top_work_centers(limit=5, **f):
    return _productivity_rows("work_center", **f)[:limit]

def bottom_work_centers(limit=5, **f):
    return list(reversed(_productivity_rows("work_center", **f)))[:limit]

def best_models(limit=5, **f):
    return _productivity_rows("model", **f)[:limit]

def worst_models(limit=5, **f):
    return list(reversed(_productivity_rows("model", **f)))[:limit]


# ── Trends over time (day/week/month/year) ───────────────────────────────────

def productivity_trend(period="day", **f):
    """Actual-vs-planned productivity % per period, piece-based."""
    trunc = _TRUNCS.get(period, TruncDay)
    dp = "hourly_plan__daily_plan"
    qs = executions_qs(**f).select_related(
        "hourly_plan", "hourly_plan__daily_plan",
        "hourly_plan__daily_plan__subprocess",
        "hourly_plan__daily_plan__subprocess__subprocess_type")
    buckets = defaultdict(lambda: {"planned_p": 0.0, "actual_p": 0.0})
    for ex in qs:
        d = ex.hourly_plan.daily_plan.date
        if period == "week":
            key = (d - dt.timedelta(days=d.weekday())).isoformat()
        elif period == "month":
            key = d.replace(day=1).isoformat()
        elif period == "year":
            key = d.replace(month=1, day=1).isoformat()
        else:
            key = d.isoformat()
        factor = _factor_for_execution(ex)
        buckets[key]["planned_p"] += _pieces(ex.hourly_plan.planned_quantity, factor)
        buckets[key]["actual_p"]  += _pieces(ex.actual_quantity, factor)
    rows = []
    for key in sorted(buckets):
        b = buckets[key]
        pct = round(b["actual_p"] / b["planned_p"] * 100, 1) if b["planned_p"] else None
        rows.append({"bucket": key, "planned_pieces": round(b["planned_p"], 2),
                     "actual_pieces": round(b["actual_p"], 2), "productivity_pct": pct})
    return rows


def planned_vs_actual_trend(period="day", **f):
    """Planned vs actual PIECES per period (for the trend line/bars)."""
    rows = productivity_trend(period=period, **f)
    return [{"bucket": r["bucket"], "planned": r["planned_pieces"],
             "actual": r["actual_pieces"]} for r in rows]


def overtime_trend(period="day", **f):
    """Overtime hours per period (count of overtime HourlyPlan rows captured)."""
    trunc = _TRUNCS.get(period, TruncDay)
    dp = "hourly_plan__daily_plan"
    qs = executions_qs(**f).filter(hourly_plan__is_overtime=True)
    buckets = defaultdict(int)
    for ex in qs.select_related("hourly_plan", "hourly_plan__daily_plan"):
        d = ex.hourly_plan.daily_plan.date
        if period == "week":
            key = (d - dt.timedelta(days=d.weekday())).isoformat()
        elif period == "month":
            key = d.replace(day=1).isoformat()
        elif period == "year":
            key = d.replace(month=1, day=1).isoformat()
        else:
            key = d.isoformat()
        buckets[key] += 1
    return [{"bucket": k, "overtime_hours": buckets[k]} for k in sorted(buckets)]


# ── One-call extended KPI bundle ─────────────────────────────────────────────

def extended_kpi_summary(**f):
    st = standard_time_and_rate(**f)
    return {
        "production_efficiency_pct": production_efficiency_pct(**f),
        "headcount_utilization":     headcount_utilization(**f),
        "standard_time_min_per_piece": st["standard_time_min_per_piece"],
        "cycle_time_min_per_piece":    st["cycle_time_min_per_piece"],
        "production_rate_pieces_per_hour": st["production_rate_pieces_per_hour"],
    }