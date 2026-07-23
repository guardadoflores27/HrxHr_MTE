# analytics/day_service.py
# ─────────────────────────────────────────────────────────────────────────────
# DAY dashboard business logic (read-only).
#
# Everything the Day view/JSON needs is computed here so the view stays thin
# and Week/Month/Year can later reuse these primitives. All quantities are
# stored in UNITS; this layer converts to PIECES using the subprocess's
# conversion factor (1 / 3 / 6 units per piece) so every total, %, and chart
# shows correct piece counts.
# ─────────────────────────────────────────────────────────────────────────────

import datetime as dt

from django.db.models import Sum, Prefetch

from planning.models import DailyPlan, HourlyPlan
from production.models import HourlyExecution, ExecutionEvent


# ── Comment classification ────────────────────────────────────────────────────

COMMENT_PLAN_ACHIEVED  = "Plan Achieved"
COMMENT_NOT_ACHIEVED   = "Plan Not Achieved"
COMMENT_EXCEEDED       = "Production Exceeded Plan"
COMMENT_NON_PRODUCTIVE = "Non-Productive Hour"
COMMENT_PENDING        = "Pending — actual not entered"

# Backward-compatible aliases (used by earlier tests / callers).
CLASS_ACHIEVED = COMMENT_PLAN_ACHIEVED
CLASS_NOT_MET  = COMMENT_NOT_ACHIEVED
CLASS_EXCEEDED = COMMENT_EXCEEDED
CLASS_PENDING  = COMMENT_PENDING


def classify_hour(planned_units, actual_units):
    """Auto-classify an hour by comparing planned vs actual (in units).

    `actual_units is None` means the operator has not captured anything yet —
    that is NOT the same as producing zero, so it is reported as pending
    instead of counting as a missed plan.
    """
    if planned_units == 0:
        return COMMENT_NON_PRODUCTIVE
    if actual_units is None:
        return COMMENT_PENDING
    if actual_units < planned_units:
        return COMMENT_NOT_ACHIEVED
    if actual_units > planned_units:
        return COMMENT_EXCEEDED
    return COMMENT_PLAN_ACHIEVED


def _fmt(value):
    """Whole number when exact, 2 dp otherwise — used for aggregated sums."""
    return int(value) if float(value).is_integer() else round(value, 2)


def units_to_pieces(units, factor):
    """Convert stored units to pieces. factor = units per piece (1/3/6).

    Returns an int when the division is exact (30 units ÷ 3 = 10, not 10.0)
    and a 2-dp float only when the remainder is real information (10 ÷ 3 =
    3.33 means a piece is genuinely incomplete). This keeps the dashboards
    readable without ever hiding a partial piece.
    """
    if not factor or factor <= 0:
        factor = 1
    value = units / factor
    return int(value) if float(value).is_integer() else round(value, 2)


# ── Filtering ─────────────────────────────────────────────────────────────────

def resolve_day_plans(day=None, work_center_id=None, subprocess_id=None,
                      shift_id=None, creator_id=None):
    """Return the DailyPlan queryset for a single day with the given filters.
    All filters are optional and independent (audit-friendly)."""
    qs = (DailyPlan.objects
          .select_related("work_center", "subprocess",
                          "subprocess__subprocess_type", "shift",
                          "operator", "created_by")
          .order_by("-date", "work_center__name"))
    if day:
        qs = qs.filter(date=day)
    if work_center_id:
        qs = qs.filter(work_center_id=work_center_id)
    if subprocess_id:
        qs = qs.filter(subprocess_id=subprocess_id)
    if shift_id:
        qs = qs.filter(shift_id=shift_id)
    if creator_id:
        qs = qs.filter(created_by_id=creator_id)
    return qs


# ── Per-plan Day report ───────────────────────────────────────────────────────

def build_day_report(plan):
    """Assemble the full read-only Day report for ONE DailyPlan.

    Returns a dict with: meta, hourly_rows, totals, model_summary — all
    piece-converted. This is the single source of truth the Day view and the
    JSON endpoint both render, so the page and its auto-refresh never diverge.
    """
    factor = plan.subprocess.conversion_factor if plan.subprocess_id else 1

    hours = (HourlyPlan.objects
             .filter(daily_plan=plan)
             .select_related("model")
             .order_by("hour"))

    # One execution per (hour, model); prefetch to avoid N+1.
    exec_by_hp = {
        e.hourly_plan_id: e
        for e in HourlyExecution.objects.filter(hourly_plan__daily_plan=plan)
    }

    hourly_rows = []
    tot_planned_u = tot_actual_u = tot_scrap_u = 0
    pending_hours = 0
    model_acc = {}   # model name -> {planned_u, actual_u}

    for hp in hours:
        ex        = exec_by_hp.get(hp.id)
        # No execution row at all means "not captured yet" — kept distinct from
        # a captured zero so the dashboard can flag it as pending instead of
        # silently counting it as a missed plan.
        captured  = ex is not None
        actual_u  = ex.actual_quantity if captured else None
        scrap_u   = ex.scrap_quantity if captured else 0
        planned_u = hp.planned_quantity

        tot_planned_u += planned_u
        tot_actual_u  += (actual_u or 0)
        tot_scrap_u   += scrap_u
        if not captured and planned_u > 0:
            pending_hours += 1

        acc = model_acc.setdefault(hp.model.name, {"planned_u": 0, "actual_u": 0})
        acc["planned_u"] += planned_u
        acc["actual_u"]  += (actual_u or 0)

        hourly_rows.append({
            "hour_12h":    hp.hour.strftime("%I:%M %p").lstrip("0"),
            "hour_sort":   hp.hour.strftime("%H:%M"),
            "is_overtime": hp.is_overtime,
            "model":       hp.model.name,
            "planned_units":  planned_u,
            "actual_units":   actual_u,
            "captured":       captured,
            "pending":        (not captured) and planned_u > 0,
            "planned_pieces": units_to_pieces(planned_u, factor),
            "actual_pieces":  (units_to_pieces(actual_u, factor)
                               if captured else None),
            "headcount":   hp.effective_headcount(),
            "planned_headcount": hp.effective_headcount(),
            "actual_headcount":  (ex.effective_actual_headcount if captured
                                  else None),
            "headcount_diff":    (ex.headcount_diff if captured else None),
            "headcount_comment": (ex.headcount_comment if captured else ""),
            "comment":     ex.active_comment if ex else "",
            "hour_status": classify_hour(planned_u, actual_u),
        })

    completion = round(tot_actual_u / tot_planned_u * 100, 1) if tot_planned_u else None

    # ── Working time ─────────────────────────────────────────────────────────
    # Every captured hour counts as 60 scheduled minutes. Operational events
    # (lunch, chair time, prep, breakdowns...) are subtracted to get the time
    # actually spent producing. Break and Lunch are split out because the
    # dashboard reports them separately.
    scheduled_hours = len(hourly_rows)
    overtime_hours  = sum(1 for r in hourly_rows if r["is_overtime"])

    event_rows = (ExecutionEvent.objects
                  .filter(execution__hourly_plan__daily_plan=plan)
                  .select_related("event_type", "event_type__category")
                  .values_list("event_type__category__code", "duration_minutes"))

    lunch_minutes = break_minutes = other_minutes = 0
    for code, minutes in event_rows:
        minutes = minutes or 0
        if code == "lunch":
            lunch_minutes += minutes
        elif code == "chair":          # chair time is the short break
            break_minutes += minutes
        else:
            other_minutes += minutes

    downtime_minutes   = lunch_minutes + break_minutes + other_minutes
    real_working_min   = max(0, scheduled_hours * 60 - downtime_minutes)

    working_time = {
        "scheduled_hours":    scheduled_hours,
        "real_working_hours": round(real_working_min / 60, 1),
        "break_minutes":      break_minutes,
        "lunch_minutes":      lunch_minutes,
        "other_downtime_min": other_minutes,
        "downtime_minutes":   downtime_minutes,
        "overtime_hours":     overtime_hours,
    }

    model_summary = []
    for name, a in sorted(model_acc.items()):
        pu, au = a["planned_u"], a["actual_u"]
        model_summary.append({
            "model":          name,
            "planned_units":  pu,
            "actual_units":   au,
            "planned_pieces": units_to_pieces(pu, factor),
            "actual_pieces":  units_to_pieces(au, factor),
            "productivity_pct": round(au / pu * 100, 1) if pu else None,
        })

    return {
        "meta": {
            "plan_id":       plan.id,
            "date":          plan.date.isoformat(),
            "work_center":   plan.work_center.name,
            "subprocess":    plan.subprocess.name if plan.subprocess_id else "—",
            "shift":         plan.shift.name if plan.shift_id else "—",
            "headcount":     plan.headcount,
            "creator":       (plan.created_by.username if plan.created_by_id else "—"),
            "creator_role":  _creator_role(plan),
            "conversion":    f"{factor} unit(s) = 1 piece",
            "conversion_factor": factor,
        },
        "hourly_rows": hourly_rows,
        "totals": {
            "planned_units":  tot_planned_u,
            "actual_units":   tot_actual_u,
            "scrap_units":    tot_scrap_u,
            "planned_pieces": units_to_pieces(tot_planned_u, factor),
            "actual_pieces":  units_to_pieces(tot_actual_u, factor),
            "difference_units":  tot_actual_u - tot_planned_u,
            "difference_pieces": units_to_pieces(tot_actual_u - tot_planned_u, factor),
            "completion_pct": completion,
            "headcount":      plan.headcount,
            "pending_hours":  pending_hours,
        },
        "working_time":  working_time,
        "model_summary": model_summary,
        "chart": {
            # Grouped bar: planned vs actual PIECES per hour, 12-h labels.
            "labels":  [r["hour_12h"] for r in hourly_rows],
            "planned": [r["planned_pieces"] for r in hourly_rows],
            "actual":  [r["actual_pieces"] for r in hourly_rows],
            "overtime_flags": [r["is_overtime"] for r in hourly_rows],
        },
    }


def _creator_role(plan):
    """Best-effort role of the plan creator, for audit display."""
    u = getattr(plan, "created_by", None)
    if not u:
        return "—"
    prof = getattr(u, "profile", None)
    if prof and getattr(prof, "role", None):
        return prof.role.title()
    if u.is_superuser:
        return "Admin"
    return "User"


def planned_vs_actual_series(plan):
    """Compact chart series (planned vs actual PIECES per hour, 12-h labels)
    for one plan. Used by the auto-refresh JSON endpoint so the chart always
    mirrors the latest DB values without a page reload."""
    report = build_day_report(plan)
    return {
        "plan_id": plan.id,
        "date":    plan.date.isoformat(),
        "unit":    "pieces",
        "conversion_factor": report["meta"]["conversion_factor"],
        **report["chart"],
        "totals":  report["totals"],
    }