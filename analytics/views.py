# analytics/views.py
# ─────────────────────────────────────────────────────────────────────────────
# Dashboard page + JSON API endpoints for Operational Events analytics.
#
# Views are thin: they parse filters, delegate ALL computation to
# analytics.services, and return JSON (for Power BI / Excel / charts) or render
# the dashboard template. No business logic lives here.
# ─────────────────────────────────────────────────────────────────────────────

import datetime as dt

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from core.models import WorkCenter, Shift, SubProcess
from planning.models import Model as PlanningModel
from production.models import EventCategory, EventType
from . import services


def _parse_filters(request):
    """Pull the common filter set from query params. Blank → None."""
    def _int(name):
        v = request.GET.get(name)
        return int(v) if v and v.isdigit() else None

    def _date(name):
        v = request.GET.get(name)
        if not v:
            return None
        try:
            return dt.date.fromisoformat(v)
        except ValueError:
            return None

    return {
        "date_from":      _date("date_from"),
        "date_to":        _date("date_to"),
        "work_center_id": _int("wc"),
        "subprocess_id":  _int("subprocess"),
        "shift_id":       _int("shift"),
        "model_id":       _int("model"),
        "operator_id":    _int("operator"),
        "category_id":    _int("category"),
        "event_type_id":  _int("event_type"),
    }


@login_required
def analytics_dashboard(request):
    """Renders the analytics dashboard shell; charts fetch data via the API."""
    f = _parse_filters(request)
    context = {
        "kpis":         services.kpi_summary(**f),
        "work_centers": WorkCenter.objects.filter(is_active=True),
        "subprocesses": SubProcess.objects.select_related("work_center")
                                  .order_by("work_center__name", "name"),
        "shifts":       Shift.objects.filter(is_active=True),
        "models":       PlanningModel.objects.all(),
        "categories":   EventCategory.objects.filter(is_active=True),
        "event_types":  EventType.objects.filter(is_active=True),
        "filters":      request.GET,
    }
    return render(request, "analytics/dashboard.html", context)


# ─── JSON API (consumable by Power BI, Excel, JS charts) ─────────────────────

@login_required
def api_kpis(request):
    return JsonResponse(services.kpi_summary(**_parse_filters(request)))


@login_required
def api_by_dimension(request, dimension):
    f = _parse_filters(request)
    fn = {
        "category":    services.by_category,
        "event_type":  services.by_event_type,
        "shift":       services.by_shift,
        "operator":    services.by_operator,
        "work_center": services.by_work_center,
        "model":       services.by_model,
    }.get(dimension)
    if fn is None:
        return JsonResponse({"error": f"Unknown dimension '{dimension}'."}, status=400)
    return JsonResponse({"dimension": dimension, "rows": fn(**f)})


@login_required
def api_over_time(request):
    f = _parse_filters(request)
    period = request.GET.get("period", "day")
    rows = services.events_over_time(period=period, **f)
    # Serialize date buckets to ISO strings for JSON.
    for r in rows:
        b = r.get("bucket")
        r["bucket"] = b.isoformat() if hasattr(b, "isoformat") else str(b)
    return JsonResponse({"period": period, "rows": rows})


@login_required
def api_pareto(request):
    return JsonResponse({"rows": services.pareto_by_category(**_parse_filters(request))})


@login_required
def api_planned_vs_actual(request):
    f = _parse_filters(request)
    data = services.planned_vs_actual(**f)
    data["plan_achievement_pct"] = services.plan_achievement_pct(**f)
    return JsonResponse(data)


# ═════════════════════════════════════════════════════════════════════════════
# DAY Dashboard (Phase 1) — read-only operational view for one DailyPlan.
# ═════════════════════════════════════════════════════════════════════════════

from django.shortcuts import get_object_or_404
from planning.models import DailyPlan
from . import day_service


@login_required
def day_dashboard(request):
    """Read-only DAY dashboard. Lists recent boards and, when a plan is
    selected (?plan=<id>), shows its full day report. Users can view but not
    edit anything here."""
    # Audit-style filters.
    wc_id      = request.GET.get("wc") or ""
    sp_id      = request.GET.get("subprocess") or ""
    shift_id   = request.GET.get("shift") or ""
    date_str   = request.GET.get("date") or ""
    creator    = request.GET.get("creator") or ""

    plans = (DailyPlan.objects
             .select_related("work_center", "subprocess", "shift", "created_by")
             .order_by("-date", "-id"))
    if wc_id.isdigit():
        plans = plans.filter(work_center_id=int(wc_id))
    if sp_id.isdigit():
        plans = plans.filter(subprocess_id=int(sp_id))
    if shift_id.isdigit():
        plans = plans.filter(shift_id=int(shift_id))
    if date_str:
        try:
            plans = plans.filter(date=dt.date.fromisoformat(date_str))
        except ValueError:
            pass
    if creator:
        plans = plans.filter(created_by__username__icontains=creator)

    # "Show more" pagination: start at 20, +5 per click via ?limit=.
    try:
        limit = max(20, int(request.GET.get("limit", 20)))
    except ValueError:
        limit = 20
    total_plans = plans.count()
    plan_list   = list(plans[:limit])

    # Selected plan → full day report.
    report = None
    selected_id = request.GET.get("plan")
    if selected_id and selected_id.isdigit():
        dp = get_object_or_404(
            DailyPlan.objects.select_related("work_center", "subprocess", "shift", "created_by"),
            id=int(selected_id))
        report = day_service.build_day_report(dp)

    return render(request, "analytics/day_dashboard.html", {
        "plans":        plan_list,
        "total_plans":  total_plans,
        "limit":        limit,
        "has_more":     total_plans > limit,
        "report":       report,
        "work_centers": WorkCenter.objects.filter(is_active=True),
        "subprocesses": SubProcess.objects.select_related("work_center")
                                  .order_by("work_center__name", "name"),
        "shifts":       Shift.objects.filter(is_active=True),
        "filters":      request.GET,
    })


@login_required
def api_day_chart(request):
    """JSON for the DAY planned-vs-actual chart (pieces). Auto-refreshable."""
    plan_id = request.GET.get("plan")
    if not (plan_id and plan_id.isdigit()):
        return JsonResponse({"error": "plan id required"}, status=400)
    dp = get_object_or_404(DailyPlan, id=int(plan_id))
    return JsonResponse(day_service.planned_vs_actual_series(dp))


# ─── PHASE 2 — Extended Analytics endpoints ──────────────────────────────────

@login_required
def api_extended_kpis(request):
    return JsonResponse(services.extended_kpi_summary(**_parse_filters(request)))


@login_required
def api_performers(request, kind):
    """Top/bottom performers. kind ∈ wc-top / wc-bottom / model-best / model-worst."""
    f = _parse_filters(request)
    fn = {
        "wc-top":     services.top_work_centers,
        "wc-bottom":  services.bottom_work_centers,
        "model-best": services.best_models,
        "model-worst":services.worst_models,
    }.get(kind)
    if fn is None:
        return JsonResponse({"error": f"Unknown kind '{kind}'."}, status=400)
    return JsonResponse({"kind": kind, "rows": fn(**f)})


@login_required
def api_trend(request, metric):
    """Trends over time. metric ∈ productivity / planned-vs-actual / overtime."""
    f = _parse_filters(request)
    period = request.GET.get("period", "day")
    if metric == "productivity":
        rows = services.productivity_trend(period=period, **f)
    elif metric == "planned-vs-actual":
        rows = services.planned_vs_actual_trend(period=period, **f)
    elif metric == "overtime":
        rows = services.overtime_trend(period=period, **f)
    else:
        return JsonResponse({"error": f"Unknown metric '{metric}'."}, status=400)
    return JsonResponse({"metric": metric, "period": period, "rows": rows})


# ─── PHASE 3 — Period dashboard (Day/Week/Month/Year, read-only) ─────────────

from . import period_service


def _parse_period(request):
    period = request.GET.get("period", "day")
    if period not in ("day", "week", "month", "year"):
        period = "day"
    anchor = dt.date.today()
    v = request.GET.get("anchor") or request.GET.get("day")
    if v:
        try:
            anchor = dt.date.fromisoformat(v)
        except ValueError:
            pass
    filters = {}
    for param, key in [("wc", "work_center_id"), ("subprocess", "subprocess_id"),
                       ("shift", "shift_id"), ("model", "model_id")]:
        val = request.GET.get(param)
        if val and val.isdigit():
            filters[key] = int(val)
    return period, anchor, filters


@login_required
def period_dashboard(request):
    """Read-only Day/Week/Month/Year dashboard with a period selector."""
    period, anchor, filters = _parse_period(request)
    report = period_service.build_period_report(period, anchor, **filters)
    return render(request, "analytics/period_dashboard.html", {
        "report":       report,
        "period":       period,
        "anchor":       anchor.isoformat(),
        "work_centers": WorkCenter.objects.filter(is_active=True),
        "subprocesses": SubProcess.objects.select_related("work_center")
                                  .order_by("work_center__name", "name"),
        "shifts":       Shift.objects.filter(is_active=True),
        "models":       PlanningModel.objects.all(),
        "filters":      request.GET,
    })


@login_required
def api_period_data(request):
    """JSON for the period dashboard charts — enables auto-refresh with no reload."""
    period, anchor, filters = _parse_period(request)
    return JsonResponse(period_service.build_period_report(period, anchor, **filters))


# ─── PHASE 4 — Excel / PDF exports ───────────────────────────────────────────

from django.http import HttpResponse
from . import export_service


def _file_response(content, filename, content_type):
    resp = HttpResponse(content, content_type=content_type)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_CT  = "application/pdf"


@login_required
def export_day(request, fmt):
    """Export the selected Day plan report. fmt ∈ excel / pdf.
    Requires ?plan=<id> (the same plan shown on the Day dashboard)."""
    plan_id = request.GET.get("plan")
    if not (plan_id and plan_id.isdigit()):
        return HttpResponse("plan id required", status=400)
    dp = get_object_or_404(DailyPlan, id=int(plan_id))
    report = day_service.build_day_report(dp)
    stamp = f"{report['meta']['work_center']}_{report['meta']['date']}"
    if fmt == "excel":
        return _file_response(export_service.day_report_to_excel(report),
                              f"day_{stamp}.xlsx", XLSX_CT)
    if fmt == "pdf":
        return _file_response(export_service.day_report_to_pdf(report),
                              f"day_{stamp}.pdf", PDF_CT)
    return HttpResponse("unknown format", status=400)


@login_required
def export_period(request, fmt):
    """Export the current Period report. fmt ∈ excel / pdf. Honors all filters."""
    period, anchor, filters = _parse_period(request)
    report = period_service.build_period_report(period, anchor, **filters)
    stamp = f"{report['meta']['period']}_{report['meta']['start']}"
    if fmt == "excel":
        return _file_response(export_service.period_report_to_excel(report),
                              f"period_{stamp}.xlsx", XLSX_CT)
    if fmt == "pdf":
        return _file_response(export_service.period_report_to_pdf(report),
                              f"period_{stamp}.pdf", PDF_CT)
    return HttpResponse("unknown format", status=400)