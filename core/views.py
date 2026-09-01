# core/views.py
# ─────────────────────────────────────────────────────────────────────────────
# COPY-PASTE → hrxhr_project/core/views.py
# ─────────────────────────────────────────────────────────────────────────────

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import WorkCenter, SubProcess, SubProcessType, Shift
from .forms  import WorkCenterForm, SubProcessForm, SubProcessTypeForm, ShiftForm
from users.decorators import admin_or_engineer, admin_engineer_or_supervisor, role_required, get_role


def _role(request):
    # Kept as a thin request-based wrapper so every existing call site in
    # this file (_role(request)) keeps working unchanged — the actual role
    # lookup now lives in one place, users.decorators.get_role.
    return get_role(request.user)


# ── Work Center ────────────────────────────────────────────────────────────────

@login_required
def wc_list(request):
    centers = WorkCenter.objects.prefetch_related("subprocess_set").all()
    search  = request.GET.get("search", "").strip()
    status  = request.GET.get("status", "").strip()

    if search:
        centers = centers.filter(name__icontains=search)
    if status == "active":
        centers = centers.filter(is_active=True)
    elif status == "inactive":
        centers = centers.filter(is_active=False)

    return render(request, "core/wc_list.html", {
        "centers": centers,
        "filter":  {"search": search, "status": status},
    })


@login_required
@admin_or_engineer
def wc_create(request):
    form = WorkCenterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Work center created successfully.")
        return redirect("core:wc_list")
    return render(request, "core/wc_form.html", {"form": form, "action": "Create Work Center"})


@login_required
@admin_or_engineer
def wc_update(request, pk):
    wc   = get_object_or_404(WorkCenter, pk=pk)
    form = WorkCenterForm(request.POST or None, instance=wc)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Work center updated.")
        return redirect("core:wc_list")
    return render(request, "core/wc_form.html",
                  {"form": form, "action": "Edit Work Center", "obj": wc})


@login_required
@admin_or_engineer
def wc_delete(request, pk):
    wc = get_object_or_404(WorkCenter, pk=pk)
    # Same "blocked while in use" safety net as planning.model_delete —
    # WorkCenter -> DailyPlan is on_delete=CASCADE, so deleting one used by
    # any Daily Plan would silently wipe out that plan's entire execution
    # history. Independent of who is allowed to delete it.
    blocking = wc.dailyplan_set.select_related("subprocess", "shift").distinct()
    if blocking.exists():
        messages.error(
            request,
            f"Can't delete '{wc.name}': it's used by {blocking.count()} Daily Plan(s). "
            f"Remove or reassign those first."
        )
        return redirect("core:wc_list")       
    if request.method == "POST":
        wc.delete()
        messages.success(request, "Work center deleted.")
        return redirect("core:wc_list")
    return render(request, "core/confirm_delete.html", {"obj": wc, "back_url": "core:wc_list"})


# ── Subprocess Type — Admin only ───────────────────────────────────────────────

def _require_admin(request):
    """Returns True if the user is admin, else adds an error message and returns False."""
    if _role(request) != "admin":
        messages.error(request, "Only Admins can manage Subprocess Types.")
        return False
    return True


@login_required
def spt_list(request):
    """List all subprocess types. Admins see full controls; others read-only."""
    spts      = SubProcessType.objects.order_by("name")
    is_admin  = _role(request) == "admin"
    return render(request, "core/spt_list.html", {
        "spts":     spts,
        "is_admin": is_admin,
    })


@login_required
@admin_or_engineer
def spt_create(request):
    if not _require_admin(request):
        return redirect("core:spt_list")

    form = SubProcessTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Subprocess type '{form.cleaned_data['name']}' created.")
        return redirect("core:spt_list")

    return render(request, "core/spt_form.html", {
        "form":   form,
        "action": "Create Subprocess Type",
    })


@login_required
@admin_or_engineer
def spt_update(request, pk):
    if not _require_admin(request):
        return redirect("core:spt_list")

    spt  = get_object_or_404(SubProcessType, pk=pk)
    form = SubProcessTypeForm(request.POST or None, instance=spt)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Subprocess type '{spt.name}' updated.")
        return redirect("core:spt_list")

    return render(request, "core/spt_form.html", {
        "form":   form,
        "action": "Edit Subprocess Type",
        "obj":    spt,
    })


@login_required
@admin_or_engineer
def spt_delete(request, pk):
    if not _require_admin(request):
        return redirect("core:spt_list")

    spt = get_object_or_404(SubProcessType, pk=pk)

    # Protect: cannot delete if subprocesses are linked
    linked = spt.subprocesses.count()
    if linked > 0:
        messages.error(
            request,
            f"Cannot delete '{spt.name}' — {linked} subprocess(es) use this type. "
            f"Reassign them first."
        )
        return redirect("core:spt_list")

    if request.method == "POST":
        name = spt.name
        spt.delete()
        messages.success(request, f"Subprocess type '{name}' deleted.")
        return redirect("core:spt_list")

    return render(request, "core/spt_confirm_delete.html", {"spt": spt})


# ── SubProcess ─────────────────────────────────────────────────────────────────

@login_required
def sp_list(request):
    subprocesses = SubProcess.objects.select_related(
        "work_center", "subprocess_type"
    ).all()
    wc_id   = request.GET.get("work_center", "").strip()
    spt_id  = request.GET.get("spt", "").strip()
    search  = request.GET.get("search", "").strip()

    if wc_id:  subprocesses = subprocesses.filter(work_center_id=wc_id)
    if spt_id: subprocesses = subprocesses.filter(subprocess_type_id=spt_id)
    if search: subprocesses = subprocesses.filter(name__icontains=search)

    return render(request, "core/sp_list.html", {
        "subprocesses":     subprocesses,
        "work_centers":     WorkCenter.objects.filter(is_active=True).order_by("name"),
        "subprocess_types": SubProcessType.objects.order_by("name"),
        "filter":           {"work_center": wc_id, "spt": spt_id, "search": search},
        "is_admin":         _role(request) == "admin",
    })


@login_required
@admin_or_engineer
def sp_create(request):
    form = SubProcessForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Subprocess created successfully.")
        return redirect("core:sp_list")
    return render(request, "core/sp_form.html", {"form": form, "action": "Create Subprocess"})


@login_required
@admin_or_engineer
def sp_update(request, pk):
    sp   = get_object_or_404(SubProcess, pk=pk)
    form = SubProcessForm(request.POST or None, instance=sp)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Subprocess updated.")
        return redirect("core:sp_list")
    return render(request, "core/sp_form.html",
                  {"form": form, "action": "Edit Subprocess", "obj": sp})


@login_required
@admin_or_engineer
def sp_delete(request, pk):
    sp = get_object_or_404(SubProcess, pk=pk)
    # Same reasoning as wc_delete above — Subprocess -> DailyPlan is also
    # on_delete=CASCADE.
    blocking = sp.dailyplan_set.select_related("work_center", "shift").distinct()
    if blocking.exists():
        messages.error(
            request,
            f"Can't delete '{sp.name}': it's used by {blocking.count()} Daily Plan(s). "
            f"Remove or reassign those first."
        )
        return redirect("core:sp_list")
    if request.method == "POST":
        sp.delete()
        messages.success(request, "Subprocess deleted.")
        return redirect("core:sp_list")
    return render(request, "core/confirm_delete.html", {"obj": sp, "back_url": "core:sp_list"})


# ── Shift — admin, engineer & supervisor only ─────────────────────────────────────────────

@login_required
@admin_engineer_or_supervisor
def shift_list(request):
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    shifts = Shift.objects.all()
    if search:
        shifts = shifts.filter(name__icontains=search) | shifts.filter(code__icontains=search)
    if status == "active":
        shifts = shifts.filter(is_active=True)
    elif status == "inactive":
        shifts = shifts.filter(is_active=False)

    shifts = shifts.order_by("start_time", "name")

    return render(request, "shifts/shift_list.html", {
        "shifts": shifts,
        "total":  Shift.objects.count(),
        "search": search,
        "status": status,
    })


@login_required
@admin_engineer_or_supervisor
def shift_create(request):
    form = ShiftForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Shift '{form.cleaned_data['name']}' created successfully.")
        return redirect("core:shift_list")
    return render(request, "shifts/shift_form.html", {"form": form, "action": "Create Shift"})


@login_required
@admin_engineer_or_supervisor
def shift_update(request, pk):
    shift = get_object_or_404(Shift, pk=pk)
    form  = ShiftForm(request.POST or None, instance=shift)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Shift '{shift.name}' updated successfully.")
        return redirect("core:shift_list")
    return render(request, "shifts/shift_form.html",
                  {"form": form, "action": "Edit Shift", "obj": shift})


@login_required
@admin_engineer_or_supervisor
def shift_delete(request, pk):
    shift = get_object_or_404(Shift, pk=pk)

    from planning.models import DailyPlan
    blocking = DailyPlan.objects.filter(shift=shift).select_related("work_center", "subprocess")

    if blocking.exists():
        return render(request, "shifts/shift_confirm_delete.html", {
            "shift":    shift,
            "blocking": blocking[:10],
            "blocked":  True,
        })

    if request.method == "POST":
        name = shift.name
        shift.delete()
        messages.success(request, f"Shift '{name}' deleted successfully.")
        return redirect("core:shift_list")

    return render(request, "shifts/shift_confirm_delete.html", {
        "shift":   shift,
        "blocked": False,
    })