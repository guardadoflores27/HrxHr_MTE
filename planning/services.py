import datetime as dt
from django.utils import timezone
from .models import DailyPlan, HourlyPlan, HourlyPlanBlock, HeadcountAudit


# ─── Shift slot generator ─────────────────────────────────────────────────────

def generate_shift_slots(shift):
    """
    Returns 1-hour time blocks for a shift window.
    Last block may be partial if shift end doesn't land on a full hour.
    Each dict: {start, end, label_12h, minutes, is_partial}
    """
    if not shift:
        return []

    base = dt.date.today()
    s    = dt.datetime.combine(base, shift.start_time)
    e    = dt.datetime.combine(base, shift.end_time)
    if e <= s:
        e += dt.timedelta(days=1)

    slots, cur = [], s
    while cur < e:
        nxt      = cur + dt.timedelta(hours=1)
        slot_end = min(nxt, e)
        mins     = int((slot_end - cur).total_seconds() / 60)

        slots.append({
            "start":      cur.strftime("%H:%M"),
            "end":        slot_end.strftime("%H:%M"),
            "label_12h":  (
                cur.strftime("%I:%M %p").lstrip("0") + " – " +
                slot_end.strftime("%I:%M %p").lstrip("0")
            ),
            "minutes":    mins,
            "is_partial": mins < 60,
        })
        cur = nxt

    return slots


# ─── Hourly board builder ─────────────────────────────────────────────────────

def get_hourly_board(plan):
    """
    Assembles all data needed to render the hourly plan dashboard.
    Returns: (time_slots, overtime_slots, hc_history)

    overtime_slots mirrors time_slots' shape — each entry is a dict with
    start/end/label_12h/minutes/rows/blocks/eff_min/total_planned — so
    Time Blocks (lunch, pre-op, etc.) can be dropped onto overtime hours
    exactly like regular ones, and "effective minutes" is computed the
    same way for both.
    """
    time_slots  = generate_shift_slots(plan.shift)
    slot_starts = {s["start"] for s in time_slots}

    hp_qs = (
        HourlyPlan.objects
        .filter(daily_plan=plan)
        .select_related("model")
        .order_by("hour")
    )

    block_qs = (
        HourlyPlanBlock.objects
        .filter(daily_plan=plan)
        .order_by("slot_time", "created_at")
    )
    blocks_by_slot = {}
    for b in block_qs:
        key = b.slot_time.strftime("%H:%M")
        blocks_by_slot.setdefault(key, []).append(b)

    rows_by_slot     = {}
    ot_rows_by_slot  = {}
    ot_slot_order    = []
    for hp in hp_qs:
        key = hp.hour.strftime("%H:%M")
        if hp.is_overtime or key not in slot_starts:
            if key not in ot_rows_by_slot:
                ot_rows_by_slot[key] = []
                ot_slot_order.append(key)
            ot_rows_by_slot[key].append(hp)
        else:
            rows_by_slot.setdefault(key, []).append(hp)

    for slot in time_slots:
        key             = slot["start"]
        slot["rows"]    = rows_by_slot.get(key, [])
        slot["blocks"]  = blocks_by_slot.get(key, [])
        used_min        = sum(b.minutes for b in slot["blocks"])
        slot["eff_min"] = max(0, slot["minutes"] - used_min)
        slot["used_min"]= used_min
        # Informational total when several models share the same hour.
        slot["total_planned"] = sum(hp.planned_quantity for hp in slot["rows"])

    # Build one slot dict per overtime hour, same shape as time_slots, so
    # the template/JS can treat them uniformly for Time Blocks purposes.
    overtime_slots = []
    for key in ot_slot_order:
        rows      = ot_rows_by_slot[key]
        first_hp  = rows[0]
        slot_min  = 60  # overtime hours are always generated as full 60-min blocks
        blocks    = blocks_by_slot.get(key, [])
        used_min  = sum(b.minutes for b in blocks)
        overtime_slots.append({
            "start":          key,
            "end":            first_hp.hour_end.strftime("%H:%M"),
            "label_12h":      (
                first_hp.hour.strftime("%I:%M %p").lstrip("0") + " – " +
                first_hp.hour_end.strftime("%I:%M %p").lstrip("0")
            ),
            "minutes":        slot_min,
            "is_partial":     False,
            "rows":           rows,
            "blocks":         blocks,
            "used_min":       used_min,
            "eff_min":        max(0, slot_min - used_min),
            "total_planned":  sum(hp.planned_quantity for hp in rows),
        })

    hc_history = list(
        HeadcountAudit.objects
        .filter(daily_plan=plan)
        .select_related("modified_by")
        .order_by("-modified_at")[:5]
    )

    return time_slots, overtime_slots, hc_history


# ─── Block operations ─────────────────────────────────────────────────────────

def format_blocks_summary(blocks):
    """
    Turns a list of HourlyPlanBlock into a single human-readable string,
    e.g. "Lunch Break (30 min) · Operation Preparation (15 min)".
    Used both as an informational note and to auto-fill Actuals comments
    (production app) when Time Blocks explain a planned/actual mismatch —
    for any hour, regular or overtime, and regardless of planned quantity.

    NOTE: This is the *display* string only. For dashboard filtering, use
    blocks_categories() / blocks_category_codes() which return the machine-
    readable category codes (lunch / preop / workfin / chair / extra),
    kept separate from any human free text.
    """
    if not blocks:
        return ""
    parts = []
    for b in blocks:
        part = b.label()
        if b.minutes:
            part += f" ({b.minutes} min)"
        parts.append(part)
    return " · ".join(parts)


def blocks_category_codes(blocks):
    """
    Returns the ordered list of unique category codes present in `blocks`,
    e.g. ["lunch", "preop"]. These codes are stable and never localized —
    they are what the dashboard filters on, independent of any label text
    or supervisor free-text comment.
    """
    seen, codes = set(), []
    for b in blocks:
        c = b.category()
        if c not in seen:
            seen.add(c)
            codes.append(c)
    return codes


def blocks_categories_joined(blocks):
    """Comma-joined category codes for embedding in a single DB column,
    e.g. "lunch,preop". Empty string when there are no blocks."""
    return ",".join(blocks_category_codes(blocks))


def add_block(daily_plan, slot_time_str, block_type, minutes, reason, user):
    slot_dt = dt.datetime.strptime(slot_time_str, "%H:%M").time()
    return HourlyPlanBlock.objects.create(
        daily_plan = daily_plan,
        slot_time  = slot_dt,
        block_type = block_type,
        minutes    = max(0, int(minutes)),
        reason     = (reason or "").strip(),
        created_by = user,
    )


def remove_block(block_id, daily_plan, user):
    try:
        HourlyPlanBlock.objects.get(id=block_id, daily_plan=daily_plan).delete()
        return True, None
    except HourlyPlanBlock.DoesNotExist:
        return False, "Block not found."


# ─── Headcount with audit ─────────────────────────────────────────────────────

def update_headcount(daily_plan, new_value, comment, user, apply_to_all=False):
    """Change the plan-level head count.

    Hours WITHOUT a per-hour override always follow the plan automatically
    (see HourlyPlan.effective_headcount). `apply_to_all=True` additionally
    clears every per-hour override, so the new value really does apply to
    every hour on the board.
    """
    if not (comment or "").strip():
        return False, "A comment is required when modifying headcount.", 0
    try:
        new_value = int(new_value)
        if new_value < 1:
            return False, "Headcount must be at least 1.", 0
    except (ValueError, TypeError):
        return False, "Invalid headcount value.", 0

    previous = daily_plan.headcount
    if previous == new_value:
        return False, "New value is the same as the current headcount.", 0

    HeadcountAudit.objects.create(
        daily_plan       = daily_plan,
        previous_value   = previous,
        new_value        = new_value,
        comment          = comment.strip(),
        modified_by      = user,
        modified_by_name = user.username if user else "",
    )
    daily_plan.headcount = new_value
    daily_plan.save(update_fields=["headcount"])

    overrides_cleared = 0
    if apply_to_all:
        overrides_cleared = (daily_plan.hourly_plans
                             .filter(headcount__isnull=False)
                             .update(headcount=None))
    return True, None, overrides_cleared


# ─── Role helpers ─────────────────────────────────────────────────────────────

def get_user_role(user):
    p = getattr(user, "profile", None)
    return p.role if p else None

def can_write(user):
    # Engineer is intentionally NOT included: per the confirmed permission
    # matrix, Engineer only has "view" on Hourly Plans
    return get_user_role(user) in {"leader", "admin", "supervisor"}

def can_move_blocks(user):
    return get_user_role(user) in {"leader", "admin", "supervisor"}

def can_edit_headcount(user):
    return get_user_role(user) in {"leader", "admin", "supervisor"}

def can_delete(user):
    return get_user_role(user) in {"leader", "admin", "supervisor"}