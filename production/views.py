# production/views.py
# hrxhr_project/production/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Prefetch
from django.db import transaction
from django.http import JsonResponse

from planning.models import DailyPlan, HourlyPlan, HourlyPlanBlock
from planning.services import format_blocks_summary, blocks_categories_joined
from core.models import WorkCenter, Shift, SubProcess
from .models import HourlyExecution, ExecutionLossReason, EventType, LossReason
from .forms import HourlyExecutionForm, ExecutionEventFormSet
from users.decorators import not_operator_write


def _build_plan_stats(plan):
    cf       = plan.subprocess.conversion_factor
    total_hp = HourlyPlan.objects.filter(daily_plan=plan).count()
    done_hp  = HourlyExecution.objects.filter(hourly_plan__daily_plan=plan).count()
    planned_pieces = (
        HourlyPlan.objects.filter(daily_plan=plan)
        .aggregate(t=Sum("planned_quantity"))["t"] or 0
    )

    if cf > 1:
        rows = (
            HourlyExecution.objects
            .filter(hourly_plan__daily_plan=plan)
            .values("hourly_plan__model__id", "hourly_plan__model__name")
            .annotate(units=Sum("actual_quantity"))
            .order_by("hourly_plan__model__name")
        )
        model_breakdown, total_completed = [], 0
        for r in rows:
            units     = r["units"] or 0
            pieces    = units // cf
            remainder = units % cf
            total_completed += pieces
            model_breakdown.append({
                "model_name": r["hourly_plan__model__name"],
                "units": units, "pieces": pieces, "remainder": remainder,
            })
    else:
        total_actual = (
            HourlyExecution.objects
            .filter(hourly_plan__daily_plan=plan)
            .aggregate(t=Sum("actual_quantity"))["t"] or 0
        )
        total_completed, model_breakdown = total_actual, []

    # Scrap is captured in units on each execution row; report the plan total
    # so the list can show it per plan and roll it up for the whole page.
    scrap_units = (
        HourlyExecution.objects.filter(hourly_plan__daily_plan=plan)
        .aggregate(t=Sum("scrap_quantity"))["t"] or 0
    )

    return {
        "conversion_factor":      cf,
        "model_breakdown":        model_breakdown,
        "total_completed_pieces": total_completed,
        "total_planned_pieces":   planned_pieces,
        "total_scrap_units":      scrap_units,
        "total_hours":            total_hp,
        "done_hours":             done_hp,
        "pct": int(done_hp / total_hp * 100) if total_hp else 0,
    }


@login_required
def execution_list(request):
    plans = DailyPlan.objects.select_related(
        "work_center", "subprocess", "shift"
    ).order_by("-date")

    date_from = request.GET.get("date_from",   "").strip()
    date_to   = request.GET.get("date_to",     "").strip()
    wc_id     = request.GET.get("work_center", "").strip()
    sp_id     = request.GET.get("subprocess",  "").strip()
    shift_id  = request.GET.get("shift",       "").strip()
    only_ot   = request.GET.get("overtime",    "").strip()

    if date_from: plans = plans.filter(date__gte=date_from)
    if date_to:   plans = plans.filter(date__lte=date_to)
    if wc_id:     plans = plans.filter(work_center_id=wc_id)
    if sp_id:     plans = plans.filter(subprocess_id=sp_id)
    if shift_id:  plans = plans.filter(shift_id=shift_id)
    # Overtime filter — three states:
    #   ""  → all plans
    #   "1" → only plans that contain at least one overtime hour
    #   "0" → only plans with no overtime hours at all
    if only_ot == "1":
        plans = plans.filter(hourly_plans__is_overtime=True).distinct()
    elif only_ot == "0":
        plans = plans.exclude(hourly_plans__is_overtime=True).distinct()

    # Prefetch the overtime rows once for the whole page instead of querying
    # per plan inside the loop (removes the N+1).
    plans = plans.prefetch_related(
        Prefetch(
            "hourly_plans",
            queryset=HourlyPlan.objects.filter(is_overtime=True)
                                       .select_related("model")
                                       .order_by("model__name"),
            to_attr="overtime_rows",
        )
    )

    enriched = []
    for plan in plans:
        stats = _build_plan_stats(plan)
        # Distinct model names that ran in overtime, from the prefetched rows.
        ot_models = sorted({r.model.name for r in plan.overtime_rows})
        enriched.append({
            "plan": plan,
            "stats": stats,
            "ot_models": ot_models,
            "has_overtime": bool(ot_models),
        })

    # Roll up scrap across every plan currently shown (respects the filters).
    total_scrap = sum(e["stats"]["total_scrap_units"] for e in enriched)

    return render(request, "production/execution_list.html", {
        "enriched":     enriched,
        "total_scrap":  total_scrap,
        "work_centers": WorkCenter.objects.filter(is_active=True).order_by("name"),
        "subprocesses": SubProcess.objects.select_related("work_center")
                                  .order_by("work_center__name", "name"),
        "shifts":       Shift.objects.filter(is_active=True).order_by("start_time"),
        "filter": {
            "date_from":   date_from, "date_to": date_to,
            "work_center": wc_id,     "subprocess": sp_id,
            "shift":       shift_id,  "overtime":   only_ot,
        },
    })


@login_required
@not_operator_write
def execution_enter(request, plan_id):
    plan  = get_object_or_404(DailyPlan, id=plan_id)
    hours = HourlyPlan.objects.filter(
        daily_plan=plan
    ).select_related("model").order_by("hour")

    # ── Pre-fetch time blocks for all slots (for planned=0 auto-reason) ──────
    blocks_qs = HourlyPlanBlock.objects.filter(daily_plan=plan).order_by("slot_time", "created_at")
    blocks_by_slot = {}
    for b in blocks_qs:
        key = b.slot_time.strftime("%H:%M")
        blocks_by_slot.setdefault(key, []).append(b)

    rows, saved_count = [], 0
    # AJAX save: when the request comes from fetch() we return JSON (updated
    # values + per-row validation errors) instead of redirecting, so the page
    # can refresh the shown quantities and show a message without reloading.
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    row_results = []   # one entry per processed row: saved value or error

    for hp in hours:
        execution = getattr(hp, "hourlyexecution", None)
        prefix    = f"hp-{hp.id}"
        event_prefix = f"{prefix}-events"

        # Auto-reason from Time Blocks — applies to ANY hour (regular or
        # overtime) that has at least one block, regardless of whether the
        # planned quantity is 0 or not. The frontend decides which comment
        # field to pre-fill based on the actual-vs-planned outcome.
        slot_key      = hp.hour.strftime("%H:%M")
        slot_blocks   = blocks_by_slot.get(slot_key, [])
        auto_reason   = format_blocks_summary(slot_blocks)
        auto_cats     = blocks_categories_joined(slot_blocks)

        if request.method == "POST":
            raw_actual = request.POST.get(f"{prefix}-actual_quantity", "").strip()
            event_formset = ExecutionEventFormSet(
                request.POST, instance=execution, prefix=event_prefix
            )

            if raw_actual == "":
                initial = {}
                if execution:
                    initial["loss_reasons"] = execution.executionlossreason_set.values_list(
                        "loss_reason_id", flat=True
                    )
                form = HourlyExecutionForm(instance=execution, prefix=prefix, initial=initial)
                rows.append({"hp": hp, "execution": execution, "form": form,
                              "auto_reason": auto_reason, "event_formset": event_formset})
                continue

            form = HourlyExecutionForm(request.POST, instance=execution, prefix=prefix)
            events_valid = event_formset.is_valid()

            if form.is_valid() and events_valid:
                actual = form.cleaned_data.get("actual_quantity") or 0
                scrap  = form.cleaned_data.get("scrap_quantity")  or 0

                # A non-productive hour (planned = 0) can never report output.
                # The UI already hides the input, but the value is clamped here
                # too so a stale template or a crafted request can't corrupt the
                # production metrics.
                if hp.planned_quantity == 0:
                    actual = 0

                # ── Server-side comment validation ────────────────────────────
                validation_errors = []

                # Head count: a difference against the plan must be explained,
                # otherwise the comparison in the reports has no context.
                actual_hc = form.cleaned_data.get("actual_headcount")
                if actual_hc is not None:
                    planned_hc = hp.effective_headcount()
                    if actual_hc != planned_hc and not \
                            form.cleaned_data.get("headcount_comment", "").strip():
                        validation_errors.append(
                            f"Hour {hp.hour.strftime('%I:%M %p')}: head count "
                            f"({actual_hc}) differs from the plan ({planned_hc}) "
                            f"— a comment is required."
                        )

                if hp.planned_quantity == 0:
                    # Non-productive hour: zero_comment is required
                    if not form.cleaned_data.get("zero_comment", "").strip():
                        validation_errors.append(
                            f"Hour {hp.hour.strftime('%I:%M %p')}: "
                            f"comment is required for non-productive hours."
                        )

                elif actual < hp.planned_quantity:
                    if not form.cleaned_data.get("loss_reasons", []):
                        validation_errors.append(
                            f"Hour {hp.hour.strftime('%I:%M %p')}: "
                            f"select at least one loss reason."
                        )
                    if not form.cleaned_data.get("comments", "").strip():
                        validation_errors.append(
                            f"Hour {hp.hour.strftime('%I:%M %p')}: "
                            f"loss comment is required."
                        )

                elif actual > hp.planned_quantity:
                    if not form.cleaned_data.get("over_comments", "").strip():
                        validation_errors.append(
                            f"Hour {hp.hour.strftime('%I:%M %p')}: "
                            f"overproduction comment is required."
                        )
                else:
                    # Plan met exactly. A comment is NEVER required here — when
                    # left blank it is auto-filled with "Plan alcanzado" on
                    # save, even if the quantity changed back to on-target.
                    pass

                if validation_errors:
                    for err in validation_errors:
                        messages.error(request, err)
                    row_results.append({
                        "hp_id": hp.id,
                        "hour":  hp.hour.strftime("%I:%M %p"),
                        "model": hp.model.name,
                        "saved": False,
                        "errors": validation_errors,
                    })
                    rows.append({"hp": hp, "execution": execution, "form": form,
                                 "auto_reason": auto_reason, "event_formset": event_formset})
                    continue

                obj = form.save(commit=False)
                obj.hourly_plan     = hp
                obj.actual_quantity = actual
                obj.scrap_quantity  = scrap

                # ── Time Blocks → their OWN structured fields ─────────────────
                # Kept entirely separate from the human comment fields so the
                # dashboard can filter by category (lunch / preop / workfin /
                # chair / extra) without parsing free text.
                obj.auto_reason     = auto_reason
                obj.auto_categories = auto_cats

                # ── Human comment: route to the field matching the situation
                # and blank every stale one (fixes lingering comments when the
                # actual quantity changes). Centralized in the model. ─────────
                situation = obj.situation
                user_text = form.cleaned_data.get(
                    HourlyExecution.SITUATION_COMMENT_FIELD[situation], ""
                )
                obj.apply_situational_comment(user_text)

                obj.scrap_comments = (
                    form.cleaned_data.get("scrap_comments", "") if scrap > 0 else ""
                )

                # ── Persist atomically so any failure rolls everything back ───
                try:
                    with transaction.atomic():
                        obj.save()

                        if situation == HourlyExecution.SITUATION_BELOW:
                            obj.executionlossreason_set.all().delete()
                            for lr in form.cleaned_data.get("loss_reasons", []):
                                ExecutionLossReason.objects.create(
                                    execution=obj, loss_reason=lr)
                        else:
                            # Any non-loss situation must not keep loss reasons.
                            obj.executionlossreason_set.all().delete()

                        # Operational Events — each its own record. Any event
                        # touched through this form counts as a human edit, so
                        # flag it to protect it from the Time Block auto-sync.
                        event_formset.instance = obj
                        new_events = event_formset.save(commit=False)
                        for ev in new_events:
                            if ev.pk is None:
                                ev.created_by = request.user
                            ev.execution     = obj
                            ev.user_modified = True
                            ev.save()
                        for ev in event_formset.deleted_objects:
                            ev.delete()
                except Exception as exc:  # pragma: no cover - defensive
                    messages.error(
                        request,
                        f"Hour {hp.hour.strftime('%I:%M %p')}: "
                        f"could not save due to an unexpected error. "
                        f"No changes were made."
                    )
                    row_results.append({
                        "hp_id": hp.id, "hour": hp.hour.strftime("%I:%M %p"),
                        "model": hp.model.name,
                        "saved": False,
                        "errors": ["Unexpected error — changes were rolled back."],
                    })
                    rows.append({"hp": hp, "execution": execution, "form": form,
                                 "auto_reason": auto_reason, "event_formset": event_formset})
                    continue

                saved_count += 1
                row_results.append({
                    "hp_id": hp.id,
                    "hour":  hp.hour.strftime("%I:%M %p"),
                    "model": hp.model.name,
                    "saved": True,
                    "actual_quantity": obj.actual_quantity,
                    "planned_quantity": hp.planned_quantity,
                    "scrap_quantity": obj.scrap_quantity,
                    "efficiency_pct": obj.efficiency_pct,
                    "diff_quantity": obj.diff_quantity,
                    "situation": situation,
                    "active_comment": obj.active_comment,
                })

                execution = obj

            else:
                if not events_valid:
                    for ef in event_formset.forms:
                        for err in ef.non_field_errors():
                            messages.error(
                                request,
                                f"Hour {hp.hour.strftime('%I:%M %p')} — Event: {err}",
                            )
                # Collect field/non-field errors so AJAX can show them inline.
                form_errs = []
                for field, errs in form.errors.items():
                    for e in errs:
                        form_errs.append(f"{field}: {e}" if field != "__all__" else e)
                row_results.append({
                    "hp_id": hp.id,
                    "hour":  hp.hour.strftime("%I:%M %p"),
                    "model": hp.model.name,
                    "saved": False,
                    "errors": form_errs or ["Invalid data."],
                })
                rows.append({"hp": hp, "execution": execution, "form": form,
                             "auto_reason": auto_reason, "event_formset": event_formset})
                continue

        else:
            initial = {}
            if execution:
                initial["loss_reasons"] = execution.executionlossreason_set.values_list(
                    "loss_reason_id", flat=True
                )
            form = HourlyExecutionForm(instance=execution, prefix=prefix, initial=initial)
            event_formset = ExecutionEventFormSet(instance=execution, prefix=event_prefix)

        rows.append({
            "hp":            hp,
            "execution":     execution,
            "form":          form,
            "auto_reason":   auto_reason,
            "event_formset": event_formset,
        })

    if request.method == "POST":
        # AJAX: return structured JSON so the page updates in place.
        if is_ajax:
            error_rows = [r for r in row_results if not r.get("saved")]
            if saved_count and not error_rows:
                message = "Execution updated successfully."
                level   = "success"
            elif saved_count and error_rows:
                message = (f"Execution updated successfully for {saved_count} row(s); "
                           f"{len(error_rows)} row(s) had errors.")
                level   = "warning"
            elif error_rows:
                message = "Nothing saved — please fix the errors shown."
                level   = "error"
            else:
                message = "No rows saved — enter at least one actual quantity."
                level   = "warning"
            return JsonResponse({
                "ok":          saved_count > 0 and not error_rows,
                "saved_count": saved_count,
                "level":       level,
                "message":     message,
                "rows":        row_results,
            })

        if saved_count:
            messages.success(request, "Execution updated successfully.")
            return redirect("production:execution_enter", plan_id=plan_id)
        elif not any(messages.get_messages(request)):
            messages.warning(request, "No rows saved — enter at least one actual quantity.")
            return redirect("production:execution_enter", plan_id=plan_id)

    return render(request, "production/execution_enter.html", {
        "plan": plan, "rows": rows,
        "event_types": EventType.objects.filter(is_active=True).order_by("order", "name"),
        # Full catalog of loss reasons, also exposed at the top level so the
        # template can render them even outside the per-row form binding.
        "loss_reasons": LossReason.objects.all().order_by("name"),
    })