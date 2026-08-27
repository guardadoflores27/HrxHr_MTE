import csv
import io
import json
import datetime as dt

from django.contrib                 import messages
from django.contrib.auth.decorators import login_required
from django.http                    import JsonResponse
from django.shortcuts               import get_object_or_404, redirect, render
from django.views.decorators.http   import require_POST

from core.models         import Shift, SubProcess, WorkCenter
from production.models   import HourlyExecution
from users.decorators    import not_operator_write

from .forms    import DailyPlanForm, HourlyPlanForm
from .models   import DailyPlan, HourlyPlan, HourlyPlanBlock, Model
from .services import (
    add_block, can_delete, can_edit_headcount, can_move_blocks,
    can_write as svc_can_write, generate_shift_slots, get_hourly_board,
    remove_block, update_headcount,
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _role(request):
    p = getattr(request.user, "profile", None)
    return p.role if p else None

def _json_error(msg, status=400):
    return JsonResponse({"ok": False, "error": msg}, status=status)

def _json_ok(data=None):
    payload = {"ok": True}
    if data:
        payload.update(data)
    return JsonResponse(payload)

def _is_hour_inside_shift(hour_time, shift):
    h = hour_time.hour * 60 + hour_time.minute
    s = shift.start_time.hour * 60 + shift.start_time.minute
    e = shift.end_time.hour * 60 + shift.end_time.minute
    if shift.crosses_midnight:
        return h >= s or h < e
    return s <= h < e


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    from django.db.models import Sum
    wc_id    = request.GET.get("wc", "").strip()
    sp_id    = request.GET.get("subprocess", "").strip()
    shift_id = request.GET.get("shift", "").strip()
    date_f   = request.GET.get("date", "").strip()
    model_id = request.GET.get("model", "").strip()

    qs = HourlyPlan.objects.select_related(
        "daily_plan__work_center", "daily_plan__subprocess",
        "daily_plan__shift", "model"
    ).order_by("-daily_plan__date", "hour", "model__name")

    if wc_id:    qs = qs.filter(daily_plan__work_center_id=wc_id)
    if sp_id:    qs = qs.filter(daily_plan__subprocess_id=sp_id)
    if shift_id: qs = qs.filter(daily_plan__shift_id=shift_id)
    if date_f:   qs = qs.filter(daily_plan__date=date_f)
    if model_id: qs = qs.filter(model_id=model_id)

    # Each HourlyPlan row is already one model in one hour, so multiple
    # models sharing the same hour simply produce multiple chart points —
    # each one explicitly labeled with its model name for the tooltip.
    chart_labels, chart_planned, chart_actual = [], [], []
    chart_models, chart_dates, chart_diff = [], [], []
    for hp in qs:
        try:    actual = hp.hourlyexecution.actual_quantity
        except HourlyExecution.DoesNotExist: actual = None
        chart_labels.append(f"{hp.hour.strftime('%H:%M')} · {hp.model.name}")
        chart_models.append(hp.model.name)
        chart_dates.append(str(hp.daily_plan.date))
        chart_planned.append(hp.planned_quantity)
        chart_actual.append(actual)
        chart_diff.append(
            (actual - hp.planned_quantity) if actual is not None else None
        )

    return render(request, "planning/dashboard.html", {
        "data":          qs,
        "work_centers":  WorkCenter.objects.filter(is_active=True),
        "subprocesses":  SubProcess.objects.select_related("work_center")
                                   .order_by("work_center__name", "name"),
        "shifts":        Shift.objects.filter(is_active=True).order_by("start_time"),
        "models":        Model.objects.all(),
        "filter":        {"wc": wc_id, "subprocess": sp_id,
                          "shift": shift_id, "date": date_f, "model": model_id},
        "has_filters":   any([wc_id, sp_id, shift_id, date_f, model_id]),
        "total_planned": sum(h.planned_quantity for h in qs),
        "total_actual":  sum(c for c in chart_actual if c is not None),
        "total_rows":    qs.count(),
        "daily_plans":   DailyPlan.objects.count(),
        "chart_labels":  json.dumps(chart_labels),
        "chart_models":  json.dumps(chart_models),
        "chart_dates":   json.dumps(chart_dates),
        "chart_planned": json.dumps(chart_planned),
        "chart_actual":  json.dumps(chart_actual),
        "chart_diff":    json.dumps(chart_diff),
    })


# ─────────────────────────────────────────────────────────────────────────────
# DAILY PLANS
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def daily_plan_list(request):
    plans = DailyPlan.objects.select_related("work_center", "subprocess", "shift").order_by("-date")
    date_from = request.GET.get("date_from", "").strip()
    date_to   = request.GET.get("date_to",   "").strip()
    wc_id     = request.GET.get("work_center","").strip()
    sp_id     = request.GET.get("subprocess", "").strip()
    shift_id  = request.GET.get("shift",      "").strip()
    if date_from: plans = plans.filter(date__gte=date_from)
    if date_to:   plans = plans.filter(date__lte=date_to)
    if wc_id:     plans = plans.filter(work_center_id=wc_id)
    if sp_id:     plans = plans.filter(subprocess_id=sp_id)
    if shift_id:  plans = plans.filter(shift_id=shift_id)
    return render(request, "planning/plan_list.html", {
        "plans":        plans,
        "work_centers": WorkCenter.objects.filter(is_active=True).order_by("name"),
        "subprocesses": SubProcess.objects.select_related("work_center")
                                  .order_by("work_center__name", "name"),
        "shifts":       Shift.objects.filter(is_active=True).order_by("start_time"),
        "filter":       {"date_from": date_from, "date_to": date_to,
                         "work_center": wc_id, "subprocess": sp_id,
                         "shift": shift_id},
        "can_write":    _role(request) in {"leader", "admin", "supervisor"},
        "can_delete_plan": _role(request) in {"leader", "admin", "supervisor"},
    })


@login_required
@not_operator_write
def daily_plan_create(request):
    if _role(request) not in {"leader", "admin", "supervisor"}:
        messages.error(request, "Only Leaders, Supervisors, and Admins can create plans.")
        return redirect("planning:daily_plan_list")
    active_shifts = Shift.objects.filter(is_active=True).order_by("start_time")
    form = DailyPlanForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        plan = form.save(commit=False)
        plan.created_by      = request.user
        plan.created_by_name = request.user.username
        plan.updated_by      = request.user
        plan.updated_by_name = request.user.username
        plan.save()
        messages.success(request, f"Plan created for {plan.shift.name} shift.")
        return redirect("planning:hourly_plan", plan_id=plan.id)
    return render(request, "planning/plan_form.html",
                  {"form": form, "action": "Create", "active_shifts": active_shifts})


@login_required
@not_operator_write
def daily_plan_update(request, pk):
    if _role(request) not in {"leader", "admin", "supervisor"}:
        messages.error(request, "Only Leaders, Supervisors, and Admins can edit plans.")
        return redirect("planning:daily_plan_list")
    plan          = get_object_or_404(DailyPlan, pk=pk)
    active_shifts = Shift.objects.filter(is_active=True).order_by("start_time")
    form          = DailyPlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.updated_by      = request.user
        p.updated_by_name = request.user.username
        p.save()
        messages.success(request, "Plan updated successfully.")
        return redirect("planning:daily_plan_list")
    return render(request, "planning/plan_form.html",
                  {"form": form, "action": "Edit", "plan": plan, "active_shifts": active_shifts})


@login_required
def daily_plan_delete(request, pk):
    if _role(request) not in {"leader", "admin", "supervisor"}:
        messages.error(request, "Only Leaders, Supervisors, and Admins can delete plans.")
        return redirect("planning:daily_plan_list")
    plan = get_object_or_404(DailyPlan, pk=pk)
    if request.method == "POST":
        plan.delete()
        messages.success(request, "Plan deleted.")
        if request.POST.get("next") == "board":
            return redirect("planning:hourly_plan_board")
        return redirect("planning:daily_plan_list")
    return render(request, "planning/plan_confirm_delete.html", {"plan": plan})


# ─────────────────────────────────────────────────────────────────────────────
# HOURLY PLAN — MAIN VIEW
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def hourly_plan_view(request, plan_id):
    plan   = get_object_or_404(DailyPlan, id=plan_id)
    w_ok   = svc_can_write(request.user)
    b_ok   = can_move_blocks(request.user)
    hc_ok  = can_edit_headcount(request.user)
    del_ok = can_delete(request.user)

    time_slots, overtime_slots, hc_history = get_hourly_board(plan)

    shift_json = None
    if plan.shift:
        shift_json = {
            "name":             plan.shift.name,
            "start":            plan.shift.start_time.strftime("%H:%M"),
            "end":              plan.shift.end_time.strftime("%H:%M"),
            "crosses_midnight": plan.shift.crosses_midnight,
        }

    total_planned = (
        sum(hp.planned_quantity for s in time_slots for hp in s["rows"]) +
        sum(hp.planned_quantity for s in overtime_slots for hp in s["rows"])
    )

    return render(request, "planning/hourly_plan.html", {
        "plan":           plan,
        "time_slots":     time_slots,
        "overtime_slots": overtime_slots,
        "hc_history":     hc_history,
        "total_planned": total_planned,
        "shift_json":    json.dumps(shift_json),
        "can_write":     w_ok,
        "can_blocks":    b_ok,
        "can_hc":        hc_ok,
        "can_delete":    del_ok,
        "can_add_model": _role(request) in {"leader", "admin", "supervisor"},
    })


@login_required
def hourly_plan_delete(request, plan_id, hp_id):
    if not svc_can_write(request.user):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return _json_error("Permission denied.", 403)
        messages.error(request, "Permission denied.")
        return redirect("planning:hourly_plan", plan_id=plan_id)

    hp = get_object_or_404(HourlyPlan, id=hp_id, daily_plan_id=plan_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # An hour may hold captured production. Deleting it also deletes that
    # execution (actuals, comments, operational events) via the FK cascade, so
    # a GET reports what would be lost and the POST is the explicit go-ahead.
    execution = HourlyExecution.objects.filter(hourly_plan=hp).first()

    if request.method != "POST":
        # Pre-flight: let the UI warn the user with real numbers.
        if is_ajax:
            return _json_ok({
                "id": hp_id,
                "has_execution": execution is not None,
                "actual_quantity": execution.actual_quantity if execution else 0,
                "confirm_required": True,
            })
        return redirect("planning:hourly_plan", plan_id=plan_id)

    lost = execution.actual_quantity if execution else None
    hp.delete()          # cascades to HourlyExecution and its events

    if is_ajax:
        return _json_ok({"id": hp_id, "deleted_execution": lost})
    if lost is not None:
        messages.success(
            request,
            f"Hour deleted, including its captured execution ({lost} produced).")
    else:
        messages.success(request, "Hour deleted successfully.")
    return redirect("planning:hourly_plan", plan_id=plan_id)


# ─────────────────────────────────────────────────────────────────────────────
# HOURLY PLAN — AJAX
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def api_add_row(request, plan_id):
    if not svc_can_write(request.user):
        return _json_error("Permission denied.", 403)
    plan = get_object_or_404(DailyPlan, id=plan_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error("Invalid JSON.")

    hour_str = data.get("hour", "").strip()
    model_id = data.get("model_id")
    qty      = data.get("quantity")
    hc_over  = data.get("headcount_override")
    is_ot    = bool(data.get("is_overtime", False))
    comments = data.get("comments", "").strip()

    if not hour_str or not model_id or qty is None:
        return _json_error("hour, model_id, and quantity are required.")

    try:
        hour_time = dt.datetime.strptime(hour_str, "%H:%M").time()
    except ValueError:
        return _json_error("Invalid time format — expected HH:MM.")

    try:
        model = Model.objects.get(id=model_id)
    except Model.DoesNotExist:
        return _json_error("Model not found.")

    try:
        qty = int(qty)
        if qty < 0:
            raise ValueError
    except (ValueError, TypeError):
        return _json_error("Invalid quantity.")

    if is_ot and plan.shift:
        if _is_hour_inside_shift(hour_time, plan.shift):
            sh = plan.shift
            return _json_error(
                f"The hour {hour_str} is part of the {sh.name} shift "
                f"({sh.start_time.strftime('%I:%M %p')} – {sh.end_time.strftime('%I:%M %p')}). "
                f"Overtime must be outside the shift window."
            )

    # ── Multiple models per hour are allowed — regular AND overtime ──────────
    # An hour slot (regular or overtime) may now contain several HourlyPlan
    # rows, one per model. We only block an exact duplicate: the same model
    # added twice to the same hour, since that would be ambiguous (which row
    # should the extra quantity belong to?).
    duplicate = HourlyPlan.objects.filter(
        daily_plan=plan, hour=hour_time, is_overtime=is_ot, model=model
    ).select_related("model").first()
    if duplicate:
        return _json_error(
            f"{model.name} is already assigned to {hour_str}"
            f"{' (overtime)' if is_ot else ''}. "
            f"Edit the existing row instead of adding it twice."
        )

    hc_val = None
    if hc_over is not None:
        try:
            hc_val = int(hc_over)
        except (ValueError, TypeError):
            pass

    hp = HourlyPlan.objects.create(
        daily_plan=plan, hour=hour_time, model=model,
        planned_quantity=qty, headcount=hc_val,
        is_overtime=is_ot, comments=comments,
    )

    h_dt   = dt.datetime.combine(dt.date.today(), hp.hour)
    h_end  = (h_dt + dt.timedelta(hours=1)).time()

    # Informational total — sum of all rows sharing this same hour (and the
    # same regular/overtime bucket), so the UI can show "3 models · 150 pcs"
    # without a reload.
    from django.db.models import Sum
    slot_total = (
        HourlyPlan.objects
        .filter(daily_plan=plan, hour=hour_time, is_overtime=is_ot)
        .aggregate(t=Sum("planned_quantity"))["t"] or 0
    )

    return _json_ok({
        "id":         hp.id,
        "hour_24":    hp.hour.strftime("%H:%M"),
        "hour_12":    hp.hour.strftime("%I:%M %p").lstrip("0"),
        "end_12":     h_end.strftime("%I:%M %p").lstrip("0"),
        "model":      hp.model.name,
        "model_id":   hp.model.id,
        "qty":        hp.planned_quantity,
        "hc":         hp.effective_headcount(),
        "comments":   hp.comments,
        "overtime":   hp.is_overtime,
        "slot_total": slot_total,
    })


@login_required
@require_POST
def api_edit_row(request, plan_id, hp_id):
    if not svc_can_write(request.user):
        return _json_error("Permission denied.", 403)
    plan = get_object_or_404(DailyPlan, id=plan_id)
    hp   = get_object_or_404(HourlyPlan, id=hp_id, daily_plan=plan)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error("Invalid JSON.")

    model_id = data.get("model_id")
    qty      = data.get("quantity")
    hc_over  = data.get("headcount_override")
    comments = data.get("comments", "").strip()

    if model_id:
        try:
            new_model = Model.objects.get(id=model_id)
        except Model.DoesNotExist:
            return _json_error("Model not found.")

        # Prevent ending up with two rows for the same model in the same hour
        # — applies to both regular and overtime hours.
        duplicate = (
            HourlyPlan.objects
            .filter(daily_plan=plan, hour=hp.hour, is_overtime=hp.is_overtime, model=new_model)
            .exclude(id=hp.id)
            .exists()
        )
        if duplicate:
            return _json_error(
                f"{new_model.name} is already assigned to "
                f"{hp.hour.strftime('%H:%M')}"
                f"{' (overtime)' if hp.is_overtime else ''}. Choose a different model."
            )
        hp.model = new_model

    if qty is not None:
        try:
            qty_int = int(qty)
            if qty_int < 0:
                raise ValueError
            hp.planned_quantity = qty_int
        except (ValueError, TypeError):
            return _json_error("Invalid quantity.")

    if hc_over is not None:
        try:
            hp.headcount = int(hc_over) if str(hc_over).strip() else None
        except (ValueError, TypeError):
            hp.headcount = None

    hp.comments = comments
    hp.save()

    from django.db.models import Sum
    slot_total = (
        HourlyPlan.objects
        .filter(daily_plan=plan, hour=hp.hour, is_overtime=hp.is_overtime)
        .aggregate(t=Sum("planned_quantity"))["t"] or 0
    )

    return _json_ok({
        "id":         hp.id,
        "model":      hp.model.name,
        "model_id":   hp.model.id,
        "qty":        hp.planned_quantity,
        "hc":         hp.effective_headcount(),
        "comments":   hp.comments,
        "slot_total": slot_total,
    })


@login_required
@require_POST
def api_add_block(request, plan_id):
    if not can_move_blocks(request.user):
        return _json_error("Permission denied.", 403)
    plan = get_object_or_404(DailyPlan, id=plan_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error("Invalid JSON.")

    slot_time  = data.get("slot_time", "").strip()
    block_type = data.get("block_type", "").strip()
    minutes    = data.get("minutes", 0)
    reason     = data.get("reason", "").strip()

    if block_type not in {t for t, _ in HourlyPlanBlock.BLOCK_TYPES}:
        return _json_error(f"Invalid block type: {block_type}")
    if not slot_time:
        return _json_error("slot_time is required.")

    # Validate total won't exceed slot duration
    from django.db.models import Sum
    try:
        slot_dt = dt.datetime.strptime(slot_time, "%H:%M").time()
    except ValueError:
        return _json_error("Invalid slot_time format.")

    existing_mins = (
        HourlyPlanBlock.objects
        .filter(daily_plan=plan, slot_time=slot_dt)
        .aggregate(t=Sum("minutes"))["t"] or 0
    )
    slot_duration = 60
    if plan.shift:
        for s in generate_shift_slots(plan.shift):
            if s["start"] == slot_time:
                slot_duration = s["minutes"]
                break

    try:
        new_minutes = int(minutes)
    except (ValueError, TypeError):
        new_minutes = 0

    if existing_mins >= slot_duration:
        return _json_error(
            "No additional Time Blocks can be added because effective "
            "production time has reached 0 minutes."
        )
    if existing_mins + new_minutes > slot_duration:
        remaining = slot_duration - existing_mins
        return _json_error(
            f"Only {remaining} min remaining in this slot ({slot_duration} min total). "
            f"Reduce the block duration to {remaining} min or less."
        )

    block = add_block(plan, slot_time, block_type, minutes, reason, request.user)
    return _json_ok({
        "block_id":   block.id,
        "label":      block.label(),
        "block_type": block.block_type,
        "minutes":    block.minutes,
        "slot_time":  block.slot_time.strftime("%H:%M"),
    })


@login_required
@require_POST
def api_edit_block(request, plan_id, block_id):
    if not can_move_blocks(request.user):
        return _json_error("Permission denied.", 403)
    plan = get_object_or_404(DailyPlan, id=plan_id)
    try:
        block = HourlyPlanBlock.objects.get(id=block_id, daily_plan=plan)
    except HourlyPlanBlock.DoesNotExist:
        return _json_error("Block not found.", 404)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error("Invalid JSON.")

    minutes = data.get("minutes")
    reason  = data.get("reason", "").strip()

    if minutes is not None:
        try:
            new_minutes = max(0, int(minutes))
        except (ValueError, TypeError):
            return _json_error("Invalid minutes value.")

        from django.db.models import Sum
        slot_time_str = block.slot_time.strftime("%H:%M")
        other_mins = (
            HourlyPlanBlock.objects
            .filter(daily_plan=plan, slot_time=block.slot_time)
            .exclude(id=block.id)
            .aggregate(t=Sum("minutes"))["t"] or 0
        )
        slot_duration = 60
        if plan.shift:
            for s in generate_shift_slots(plan.shift):
                if s["start"] == slot_time_str:
                    slot_duration = s["minutes"]
                    break

        if other_mins + new_minutes > slot_duration:
            remaining = max(0, slot_duration - other_mins)
            if remaining == 0:
                return _json_error(
                    "No additional Time Blocks can be added because effective "
                    "production time has reached 0 minutes."
                )
            return _json_error(
                f"Block duration cannot exceed {remaining} min remaining in this slot."
            )
        block.minutes = new_minutes

    if block.block_type == HourlyPlanBlock.BLOCK_EXTRA:
        block.reason = reason

    block.save()
    return _json_ok({
        "block_id":   block.id,
        "label":      block.label(),
        "minutes":    block.minutes,
        "block_type": block.block_type,
        "slot_time":  block.slot_time.strftime("%H:%M"),
    })


@login_required
def api_remove_block(request, plan_id, block_id):
    if request.method not in ("DELETE", "POST"):
        return _json_error("Method not allowed.", 405)
    if not can_move_blocks(request.user):
        return _json_error("Permission denied.", 403)
    plan = get_object_or_404(DailyPlan, id=plan_id)
    ok, err = remove_block(block_id, plan, request.user)
    if not ok:
        return _json_error(err, 404)
    return _json_ok({"block_id": block_id})


@login_required
@require_POST
def api_update_headcount(request, plan_id):
    if not can_edit_headcount(request.user):
        return _json_error("Permission denied.", 403)
    plan = get_object_or_404(DailyPlan, id=plan_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error("Invalid JSON.")
    ok, err, cleared = update_headcount(
        plan, data.get("new_value"), data.get("comment", ""), request.user,
        apply_to_all=bool(data.get("apply_to_all")),
    )
    if not ok:
        return _json_error(err)
    return _json_ok({"new_headcount": plan.headcount,
                     "overrides_cleared": cleared})


@login_required
def api_get_blocks(request, plan_id):
    plan   = get_object_or_404(DailyPlan, id=plan_id)
    blocks = HourlyPlanBlock.objects.filter(daily_plan=plan).order_by("slot_time", "created_at")
    return _json_ok({"blocks": [
        {"id": b.id, "slot_time": b.slot_time.strftime("%H:%M"),
         "block_type": b.block_type, "label": b.label(), "minutes": b.minutes}
        for b in blocks
    ]})


# ─────────────────────────────────────────────────────────────────────────────
# HOURLY PLAN BOARD
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def hourly_plan_board(request):
    wc_id    = request.GET.get("work_center", "").strip()
    sp_id    = request.GET.get("subprocess",  "").strip()
    date_f   = request.GET.get("date",        "").strip()
    shift_id = request.GET.get("shift",       "").strip()
    only_ot  = request.GET.get("overtime",    "").strip()

    plans_qs = DailyPlan.objects.select_related(
        "work_center", "subprocess", "shift"
    ).prefetch_related("hourly_plans__model").order_by("date", "subprocess__name")

    if wc_id:    plans_qs = plans_qs.filter(work_center_id=wc_id)
    if sp_id:    plans_qs = plans_qs.filter(subprocess_id=sp_id)
    if date_f:   plans_qs = plans_qs.filter(date=date_f)
    if shift_id: plans_qs = plans_qs.filter(shift_id=shift_id)
    # Overtime filter: "" → all plans, "1" → only plans containing overtime hours.
    if only_ot == "1":
        plans_qs = plans_qs.filter(hourly_plans__is_overtime=True).distinct()

    board_cards = []
    for plan in plans_qs:
        raw_rows = plan.hourly_plans.select_related("model").order_by("hour")
        enriched = []
        for r in raw_rows:
            h_dt  = dt.datetime.combine(dt.date.today(), r.hour)
            h_end = (h_dt + dt.timedelta(hours=1)).time()
            enriched.append({
                "id":               r.id,
                "hour":             r.hour,
                "hour_end":         h_end,
                "hour_12":          r.hour.strftime("%I:%M %p").lstrip("0"),
                "hour_end_12":      h_end.strftime("%I:%M %p").lstrip("0"),
                "model_name":       r.model.name,
                "planned_quantity": r.planned_quantity,
                "is_overtime":      r.is_overtime,
            })
        board_cards.append({
            "plan":          plan,
            "rows":          enriched,
            "total_planned": sum(r["planned_quantity"] for r in enriched),
        })

    subprocesses = (
        SubProcess.objects.filter(work_center_id=wc_id).order_by("name")
        if wc_id
        else SubProcess.objects.select_related("work_center").order_by("work_center__name", "name")
    )

    return render(request, "planning/hourly_plan_board.html", {
        "board_cards":     board_cards,
        "work_centers":    WorkCenter.objects.filter(is_active=True).order_by("name"),
        "subprocesses":    subprocesses,
        "shifts":          Shift.objects.filter(is_active=True).order_by("start_time"),
        "filter":          {"work_center": wc_id, "subprocess": sp_id,
                            "date": date_f, "shift": shift_id,
                            "overtime": only_ot},
        "can_write":       _role(request) in {"leader", "admin", "supervisor"},
        "can_delete_plan": _role(request) in {"leader", "admin", "supervisor"},
    })


# ─────────────────────────────────────────────────────────────────────────────
# MODEL CATALOG
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def model_list(request):
    search    = request.GET.get("q", "").strip()
    can_write = _role(request) in {"leader", "admin", "supervisor"}
    from django.db.models import Count
    models_qs = Model.objects.annotate(hourly_count=Count("hourlyplan")).order_by("name")
    if search:
        models_qs = models_qs.filter(name__icontains=search)

    if request.method == "POST":
        if not can_write:
            messages.error(request, "Your role does not allow uploading models.")
            return redirect("planning:model_list")
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "No file selected.")
            return redirect("planning:model_list")
        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Only .csv files are allowed.")
            return redirect("planning:model_list")
        try:
            text = csv_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            csv_file.seek(0)
            text = csv_file.read().decode("latin-1")
        reader   = csv.reader(io.StringIO(text))
        incoming = [row[0].strip() for row in reader if row and row[0].strip()]
        if not incoming:
            messages.warning(request, "CSV file has no valid names.")
            return redirect("planning:model_list")
        existing_lower = {n.lower() for n in Model.objects.values_list("name", flat=True)}
        to_create, duplicates, seen = [], [], set()
        for name in incoming:
            key = name.lower()
            if key in existing_lower or key in seen:
                duplicates.append(name)
            else:
                to_create.append(name)
                seen.add(key)
        created = Model.objects.bulk_create([Model(name=n) for n in to_create])
        parts = []
        if created:    parts.append(f"✅ {len(created)} model(s) added.")
        if duplicates: parts.append(f"⚠️ {len(duplicates)} duplicate(s) skipped.")
        (messages.success if created else messages.warning)(request, " ".join(parts))
        return redirect("planning:model_list")

    return render(request, "planning/model_list.html", {
        "models_qs": models_qs,
        "search":    search,
        "total":     Model.objects.count(),
        "can_write": can_write,
    })


@login_required
def model_delete(request, pk):
    if _role(request) not in {"leader", "admin", "supervisor"}:
        return JsonResponse({"ok": False, "error": "Permission denied."}, status=403)
    model = get_object_or_404(Model, pk=pk)
    blocking = DailyPlan.objects.filter(
        hourly_plans__model=model
    ).select_related("work_center", "subprocess").distinct()
    if blocking.exists():
        return JsonResponse({
            "ok": False, "model_name": model.name,
            "blocking_plans": [
                {"id": p.id, "date": str(p.date),
                 "work_center": p.work_center.name, "subprocess": p.subprocess.name}
                for p in blocking
            ],
        })
    if request.method == "POST":
        model.delete()
        return JsonResponse({"ok": True, "model_name": model.name})
    return JsonResponse({"ok": False, "error": "Method not allowed."}, status=405)


# ─────────────────────────────────────────────────────────────────────────────
# GENERAL AJAX
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def subprocess_by_workcenter(request):
    wc_id = request.GET.get("work_center_id")
    if not wc_id:
        return JsonResponse({"subprocesses": []})
    subs = SubProcess.objects.filter(work_center_id=wc_id).values("id", "name")
    return JsonResponse({"subprocesses": list(subs)})


@login_required
def api_model_search(request):
    q      = request.GET.get("q", "").strip()
    models = Model.objects.filter(name__icontains=q).order_by("name")[:20]
    return JsonResponse({
        "models":        [{"id": m.id, "name": m.name} for m in models],
        "can_add_model": _role(request) in {"leader", "supervisor", "admin"},
    })