# analytics/period_service.py
# ─────────────────────────────────────────────────────────────────────────────
# WEEK / MONTH / YEAR aggregation (read-only), built on the Phase 1-2 primitives.
#
# The spec says Week/Month/Year are "same as Day but aggregated". This service
# resolves a period into a date range, then aggregates planned/actual (units +
# pieces), comment distribution, units-vs-pieces, working hours and overtime.
# Reuses units_to_pieces / classify_hour (day_service) and the trend helpers
# (services) so the numbers always match the Day dashboard and Analytics page.
# ─────────────────────────────────────────────────────────────────────────────

import calendar
import datetime as dt
from collections import defaultdict

from planning.models import HourlyPlan
from production.models import HourlyExecution
from .day_service import units_to_pieces, classify_hour, _fmt
from . import services


# ── Period → date range ───────────────────────────────────────────────────────

def resolve_range(period, anchor):
    """Return (start_date, end_date, label) for the period containing `anchor`.
    period ∈ day / week / month / year. Week is ISO (Mon–Sun)."""
    if period == "day":
        return anchor, anchor, anchor.isoformat()
    if period == "week":
        start = anchor - dt.timedelta(days=anchor.weekday())   # Monday
        end   = start + dt.timedelta(days=6)                   # Sunday
        return start, end, f"Week of {start.isoformat()} (ISO {start.isocalendar()[1]})"
    if period == "month":
        start = anchor.replace(day=1)
        last  = calendar.monthrange(anchor.year, anchor.month)[1]
        end   = anchor.replace(day=last)
        return start, end, anchor.strftime("%B %Y")
    if period == "year":
        start = anchor.replace(month=1, day=1)
        end   = anchor.replace(month=12, day=31)
        return start, end, str(anchor.year)
    # Fallback: treat as day.
    return anchor, anchor, anchor.isoformat()


# ── Executions in range with all reporting joins ──────────────────────────────

def _executions_in_range(start, end, **filters):
    return services.executions_qs(date_from=start, date_to=end, **filters).select_related(
        "hourly_plan", "hourly_plan__model", "hourly_plan__daily_plan",
        "hourly_plan__daily_plan__work_center",
        "hourly_plan__daily_plan__subprocess",
        "hourly_plan__daily_plan__subprocess__subprocess_type")


def _factor(ex):
    sp = ex.hourly_plan.daily_plan.subprocess
    if sp and sp.subprocess_type_id:
        return sp.subprocess_type.units_per_piece or 1
    return 1


# ── Full period report ────────────────────────────────────────────────────────

def build_period_report(period, anchor, **filters):
    """Aggregate everything the period dashboard needs for the given window."""
    start, end, label = resolve_range(period, anchor)
    qs = _executions_in_range(start, end, **filters)

    tot_planned_u = tot_actual_u = tot_scrap_u = 0
    tot_planned_p = tot_actual_p = 0.0
    scheduled_hours = 0
    overtime_hours  = 0
    comment_dist    = defaultdict(int)
    model_acc       = defaultdict(lambda: {"planned_u": 0, "actual_u": 0,
                                           "planned_p": 0.0, "actual_p": 0.0})

    for ex in qs:
        hp        = ex.hourly_plan
        factor    = _factor(ex)
        planned_u = hp.planned_quantity
        actual_u  = ex.actual_quantity
        planned_p = units_to_pieces(planned_u, factor)
        actual_p  = units_to_pieces(actual_u, factor)

        tot_planned_u += planned_u
        tot_actual_u  += actual_u
        tot_scrap_u   += ex.scrap_quantity
        tot_planned_p += planned_p
        tot_actual_p  += actual_p
        scheduled_hours += 1
        if hp.is_overtime:
            overtime_hours += 1

        comment_dist[classify_hour(planned_u, actual_u)] += 1

        a = model_acc[hp.model.name]
        a["planned_u"] += planned_u
        a["actual_u"]  += actual_u
        a["planned_p"] += planned_p
        a["actual_p"]  += actual_p

    # Downtime split (planned/unplanned) via the existing KPI service.
    downtime_planned   = services.planned_downtime_minutes(date_from=start, date_to=end, **filters)
    downtime_unplanned = services.unplanned_downtime_minutes(date_from=start, date_to=end, **filters)
    real_working_min   = max(0, scheduled_hours * 60 - downtime_planned - downtime_unplanned)

    completion = round(tot_actual_u / tot_planned_u * 100, 1) if tot_planned_u else None

    model_summary = []
    for name, a in sorted(model_acc.items()):
        prod = round(a["actual_p"] / a["planned_p"] * 100, 1) if a["planned_p"] else None
        model_summary.append({
            "model": name,
            "planned_units": a["planned_u"], "actual_units": a["actual_u"],
            "planned_pieces": _fmt(a["planned_p"]),
            "actual_pieces": _fmt(a["actual_p"]),
            "productivity_pct": prod,
        })

    # Trend inside the period (piece-based), reusing Phase 2 helpers.
    inner_period = "day" if period in ("day", "week") else ("week" if period == "month" else "month")
    pva_trend = services.planned_vs_actual_trend(period=inner_period, date_from=start, date_to=end, **filters)
    prod_trend = services.productivity_trend(period=inner_period, date_from=start, date_to=end, **filters)

    return {
        "meta": {
            "period": period, "label": label,
            "start": start.isoformat(), "end": end.isoformat(),
            "inner_period": inner_period,
        },
        "totals": {
            "planned_units": tot_planned_u, "actual_units": tot_actual_u,
            "scrap_units": tot_scrap_u,
            "planned_pieces": _fmt(tot_planned_p),
            "actual_pieces": _fmt(tot_actual_p),
            "difference_units": tot_actual_u - tot_planned_u,
            "difference_pieces": _fmt(tot_actual_p - tot_planned_p),
            "completion_pct": completion,
        },
        "units_vs_pieces": {
            "planned_units": tot_planned_u, "planned_pieces": _fmt(tot_planned_p),
            "actual_units": tot_actual_u,   "actual_pieces": _fmt(tot_actual_p),
        },
        "working_hours": {
            "scheduled_hours": scheduled_hours,
            "real_working_hours": round(real_working_min / 60, 1),
            "planned_downtime_min": downtime_planned,
            "unplanned_downtime_min": downtime_unplanned,
            "overtime_hours": overtime_hours,
        },
        "comment_distribution": [
            {"type": k, "count": v} for k, v in
            sorted(comment_dist.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "model_summary": model_summary,
        "trend": {
            "planned_vs_actual": pva_trend,
            "productivity": prod_trend,
        },
    }