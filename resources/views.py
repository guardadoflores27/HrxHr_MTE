# production/views.py
# hrxhr_project/production/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum

from planning.models import DailyPlan, HourlyPlan, HourlyPlanBlock
from planning.services import format_blocks_summary, blocks_categories_joined
from core.models import WorkCenter, Shift
from .models import HourlyExecution, ExecutionLossReason, EventType
from .forms import HourlyExecutionForm, ExecutionEventFormSet


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

    return {
        "conversion_factor":      cf,
        "model_breakdown":        model_breakdown,
        "total_completed_pieces": total_completed,
        "total_planned_pieces":   planned_pieces,
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
    shift_id  = request.GET.get("shift",       "").strip()
    only_ot   = request.GET.get("overtime",    "").strip()

    if date_from: plans = plans.filter(date__gte=date_from)
    if date_to:   plans = plans.filter(date__lte=date_to)
    if wc_id:     plans = plans.filter(work_center_id=wc_id)
    if shift_id:  plans = plans.filter(shift_id=shift_id)
    if only_ot == "1":
        plans = plans.filter(hourlyplan__is_overtime=True).distinct()

    enriched = []
    for plan in plans:
        stats     = _build_plan_stats(plan)
        ot_models = list(
            HourlyPlan.objects.filter(daily_plan=plan, is_overtime=True)
            .values_list("model__name", flat=True).distinct().order_by("model__name")
        )
        enriched.append({"plan": plan, "stats": stats, "ot_models": ot_models})

    return render(request, "production/execution_list.html", {
        "enriched":     enriched,
        "work_centers": WorkCenter.objects.filter(is_active=True).order_by("name"),
        "shifts":       Shift.objects.filter(is_active=True).order_by("start_time"),
        "filter": {
            "date_from":   date_from, "date_to": date_to,
            "work_center": wc_id,     "shift":   shift_id,
            "overtime":    only_ot,
        },
    })


@login_required
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

                # ── Server-side comment validation ────────────────────────────
                validation_errors = []

                if hp.planned_quantity == 0:
                    # Non-productive hour: zero_comment is now required
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
                    # Plan met exactly — no comment required; when left blank
                    # it is auto-filled with "Plan alcanzado" on save.
                    pass

                if validation_errors:
                    for err in validation_errors:
                        messages.error(request, err)
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

                # ── Assign HUMAN comments by situation ────────────────────────
                # Each branch only touches the free-text comment fields; the
                # Time Blocks summary above is never concatenated into them.
                if hp.planned_quantity == 0:
                    # Non-productive hour — clear all standard comments,
                    # keep only the optional manual zero_comment
                    obj.comments      = ""
                    obj.over_comments = ""
                    obj.ok_comments   = ""
                    obj.zero_comment  = form.cleaned_data.get("zero_comment", "").strip()

                elif actual < hp.planned_quantity:
                    obj.comments      = form.cleaned_data.get("comments", "")
                    obj.over_comments = ""
                    obj.ok_comments   = ""
                    obj.zero_comment  = ""

                elif actual > hp.planned_quantity:
                    obj.over_comments = form.cleaned_data.get("over_comments", "")
                    obj.comments      = ""
                    obj.ok_comments   = ""
                    obj.zero_comment  = ""

                else:
                    # Plan met exactly. If the supervisor wrote nothing, the
                    # comment is auto-set to "Plan alcanzado".
                    user_ok = form.cleaned_data.get("ok_comments", "").strip()
                    obj.ok_comments   = user_ok or "Plan alcanzado"
                    obj.comments      = ""
                    obj.over_comments = ""
                    obj.zero_comment  = ""

                obj.scrap_comments = (
                    form.cleaned_data.get("scrap_comments", "") if scrap > 0 else ""
                )
                obj.save()
                saved_count += 1

                if actual < hp.planned_quantity:
                    obj.executionlossreason_set.all().delete()
                    for lr in form.cleaned_data.get("loss_reasons", []):
                        ExecutionLossReason.objects.create(execution=obj, loss_reason=lr)
                else:
                    obj.executionlossreason_set.all().delete()

                # ── Operational Events — each one its own independent record,
                # never concatenated into a comment field ─────────────────────
                event_formset.instance = obj
                new_events = event_formset.save(commit=False)
                for ev in new_events:
                    if ev.pk is None:
                        ev.created_by = request.user
                    ev.execution = obj
                    ev.save()
                for ev in event_formset.deleted_objects:
                    ev.delete()

                execution = obj

            else:
                if not events_valid:
                    for ef in event_formset.forms:
                        for err in ef.non_field_errors():
                            messages.error(
                                request,
                                f"Hour {hp.hour.strftime('%I:%M %p')} — Event: {err}",
                            )
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
        if saved_count:
            messages.success(request, f"{saved_count} row(s) saved successfully.")
            return redirect("production:execution_enter", plan_id=plan_id)
        elif not any(messages.get_messages(request)):
            messages.warning(request, "No rows saved — enter at least one actual quantity.")
            return redirect("production:execution_enter", plan_id=plan_id)

    return render(request, "production/execution_enter.html", {
        "plan": plan, "rows": rows,
        "event_types": EventType.objects.filter(is_active=True).order_by("order", "name"),
    })