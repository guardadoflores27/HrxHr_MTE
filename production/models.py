# production/models.py
# hrxhr_project/production/models.py


from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from planning.models import HourlyPlan


class HourlyExecution(models.Model):
    hourly_plan     = models.OneToOneField(HourlyPlan, on_delete=models.CASCADE)

    # ── Quantities ────────────────────────────────────────────────────────────
    # min_value enforced at form layer; DB stores as-is for integrity
    actual_quantity = models.IntegerField(default=0)
    scrap_quantity  = models.IntegerField(default=0)
    # How many people ACTUALLY worked this hour. Null means "not captured",
    # which is different from zero — the reports fall back to the planned
    # headcount so historical rows keep working.
    actual_headcount = models.IntegerField(
        null=True, blank=True,
        help_text="People who actually worked this hour. Blank = not captured.",
    )
    headcount_comment = models.TextField(
        blank=True, default="",
        help_text="Required when the actual headcount differs from the plan.",
    )

    # ── Comments by situation ─────────────────────────────────────────────────
    # Below plan
    comments        = models.TextField(blank=True, default='',
                                       verbose_name="Loss reason comment")
    # Scrap occurred
    scrap_comments  = models.TextField(blank=True, default='',
                                       verbose_name="Scrap comment")
    # Over plan
    over_comments   = models.TextField(blank=True, default='',
                                       verbose_name="Overproduction comment")
    # On target
    ok_comments     = models.TextField(blank=True, default='',
                                       verbose_name="Satisfactory comment")
    # Planned = 0 AND actual = 0  (non-productive hour, manual user note)
    zero_comment    = models.TextField(
        blank=True, default='',
        verbose_name="Non-productive hour comment",
        help_text="Optional manual note when both planned and actual are 0.",
    )

    # ── Time Blocks (structured, auto-filled — NEVER the human comment) ────────
    # These two fields keep the Time Blocks information SEPARATE from the
    # supervisor's free-text comment, so the dashboard can filter cleanly by
    # category without parsing prose.
    #
    #   auto_reason      → human-readable summary, e.g.
    #                      "Lunch Break (30 min) · Operation Preparation (15 min)"
    #   auto_categories  → comma-joined machine codes, e.g. "lunch,preop"
    #                      (one or more of: lunch / preop / workfin / chair / extra)
    auto_reason     = models.TextField(
        blank=True, default='',
        verbose_name="Time Blocks summary (auto)",
        help_text="Auto-generated from planning Time Blocks. Not a human comment.",
    )
    auto_categories = models.CharField(
        max_length=120, blank=True, default='',
        verbose_name="Time Blocks categories (auto)",
        help_text="Comma-joined category codes for dashboard filtering "
                  "(lunch, preop, workfin, chair, extra).",
    )

    class Meta:
        verbose_name = "Hourly Execution"

    def __str__(self):
        return (f"Execution {self.hourly_plan} — "
                f"actual={self.actual_quantity}, scrap={self.scrap_quantity}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def is_non_productive(self):
        """True when the hour was intentionally planned as 0 and no production occurred."""
        return (self.hourly_plan.planned_quantity == 0
                and self.actual_quantity == 0)

    @property
    def is_unplanned_production(self):
        """True when planned=0 but actual>0 (unplanned / extra production)."""
        return (self.hourly_plan.planned_quantity == 0
                and self.actual_quantity > 0)

    @property
    def diff_quantity(self):
        """Actual minus planned — positive means overproduction, negative a shortfall."""
        return self.actual_quantity - self.hourly_plan.planned_quantity

    # ── Head count: planned vs actual ────────────────────────────────────
    @property
    def planned_headcount(self):
        """Head count the hour was planned with (per-hour override or plan)."""
        return self.hourly_plan.effective_headcount()

    @property
    def effective_actual_headcount(self):
        """Captured head count, falling back to the planned one when the hour
        predates this field or was simply never filled in."""
        return (self.actual_headcount
                if self.actual_headcount is not None
                else self.planned_headcount)

    @property
    def headcount_diff(self):
        """Actual minus planned people. Negative means the line ran short."""
        return self.effective_actual_headcount - self.planned_headcount

    @property
    def headcount_matches_plan(self):
        return self.headcount_diff == 0

    @property
    def efficiency_pct(self):
        """EFF% — None when planned=0 (undefined, not a loss)."""
        planned = self.hourly_plan.planned_quantity
        if planned == 0:
            return None
        return round(self.actual_quantity / planned * 100, 1)

    @property
    def active_comment(self):
        """Whichever situational HUMAN comment applies to this row — never
        shared across models, since each HourlyExecution belongs to exactly
        one HourlyPlan row (one model in one hour). This intentionally does
        NOT include auto_reason: Time Blocks live in their own fields."""
        return (self.comments or self.over_comments or
                self.ok_comments or self.zero_comment or "")

    @property
    def auto_category_list(self):
        """Structured Time Blocks categories as a clean list, e.g.
        ['lunch', 'preop']. This is what the dashboard filters on."""
        return [c for c in (self.auto_categories or "").split(",") if c]

    # Canonical category codes → dashboard-friendly labels. Kept here so the
    # dashboard can build filter chips without hardcoding strings elsewhere.
    CATEGORY_LABELS = {
        "lunch":   "Lunch Break",
        "preop":   "Operation Preparation",
        "workfin": "Work Finalization",
        "chair":   "Chair Time",
        "extra":   "Extra Reason",
    }

    @property
    def auto_category_labels(self):
        """Human-readable labels for each structured category on this row."""
        return [self.CATEGORY_LABELS.get(c, c) for c in self.auto_category_list]

    # Auto-comment written when planned exactly equals actual and the user
    # left the satisfactory note blank. Centralized here (not in the view) so
    # every entry point behaves identically. Spanish per project convention.
    PLAN_ACHIEVED_TEXT = "Plan alcanzado"

    @property
    def is_plan_achieved(self):
        """True when a productive hour hit its target exactly."""
        planned = self.hourly_plan.planned_quantity
        return planned > 0 and self.actual_quantity == planned

    def resolve_ok_comment(self, user_text=""):
        """Return the satisfactory comment to store: the user's own words if
        provided, otherwise the automatic 'Plan alcanzado'. Never overwrites
        non-empty user input."""
        user_text = (user_text or "").strip()
        return user_text or self.PLAN_ACHIEVED_TEXT

    # ── Situation classification & comment routing ────────────────────────────
    # A single source of truth for "which situation is this row in" and "which
    # comment field belongs to it". Centralizing this here removes the four
    # duplicated if/elif blocks in the view and guarantees that changing the
    # actual quantity always clears the comments that no longer apply.

    SITUATION_ZERO  = "zero"    # planned == 0 (non-productive hour)
    SITUATION_BELOW = "below"   # actual < planned  (loss)
    SITUATION_OVER  = "over"    # actual > planned  (overproduction)
    SITUATION_OK    = "ok"      # actual == planned (target met)

    # Which comment field holds the human note for each situation.
    SITUATION_COMMENT_FIELD = {
        SITUATION_ZERO:  "zero_comment",
        SITUATION_BELOW: "comments",
        SITUATION_OVER:  "over_comments",
        SITUATION_OK:    "ok_comments",
    }
    ALL_SITUATION_COMMENT_FIELDS = (
        "comments", "over_comments", "ok_comments", "zero_comment",
    )

    @property
    def situation(self):
        """Classify this row against its plan. Uses the row's own quantities."""
        planned = self.hourly_plan.planned_quantity
        if planned == 0:
            return self.SITUATION_ZERO
        if self.actual_quantity < planned:
            return self.SITUATION_BELOW
        if self.actual_quantity > planned:
            return self.SITUATION_OVER
        return self.SITUATION_OK

    def apply_situational_comment(self, user_text=""):
        """Store `user_text` in the comment field matching the current
        situation and BLANK every other situational comment, so a stale note
        from a previous actual value can never linger. For the 'ok' situation
        a blank note falls back to 'Plan alcanzado'. Does not touch
        scrap_comments (handled separately) or the auto Time-Block fields."""
        situation = self.situation
        target    = self.SITUATION_COMMENT_FIELD[situation]

        # Clear all situational comment fields first — this is the fix that
        # guarantees no comment survives that doesn't match the new value.
        for field in self.ALL_SITUATION_COMMENT_FIELDS:
            setattr(self, field, "")

        if situation == self.SITUATION_OK:
            value = self.resolve_ok_comment(user_text)
        else:
            value = (user_text or "").strip()
        setattr(self, target, value)
        return situation


class LossReason(models.Model):
    name       = models.CharField(max_length=100)
    is_default = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name        = "Loss Reason"
        verbose_name_plural = "Loss Reasons"
        ordering            = ['name']


class ExecutionLossReason(models.Model):
    execution   = models.ForeignKey(HourlyExecution, on_delete=models.CASCADE)
    loss_reason = models.ForeignKey(LossReason, on_delete=models.CASCADE)

    class Meta:
        verbose_name        = "Execution Loss Reason"
        verbose_name_plural = "Execution Loss Reasons"


# ─────────────────────────────────────────────────────────────────────────────
# Operational Events
#
# Non-productive / non-comment activities (Lunch, Chair Time, Meeting, etc.)
# used to live as free text inside HourlyExecution.comments. That made
# reporting on time buckets impossible without parsing prose.
#
# EventType is an admin-managed catalog — new event kinds can be added
# without touching code. ExecutionEvent is a first-class, one-to-many child
# of HourlyExecution: every operational event is its own row, never
# concatenated text or JSON stuffed into a comment field.
# ─────────────────────────────────────────────────────────────────────────────

class EventCategory(models.Model):
    """Canonical, dashboard-facing dimension that both planning Time Blocks
    and production Event Types roll up to. Having a single Category entity
    (instead of a hardcoded string on each side) is what makes 'Events per
    Category' / 'Total Time by Category' a trivial GROUP BY instead of a
    string-parsing exercise.

    `code` is stable and machine-readable (never localized); `name` is the
    human label shown in the UI and reports."""

    # Canonical codes shared with planning.HourlyPlanBlock.block_type so the
    # two worlds map 1:1. Kept as constants to avoid hardcoded strings.
    CODE_LUNCH    = "lunch"
    CODE_PREOP    = "preop"
    CODE_WORKFIN  = "workfin"
    CODE_CHAIR    = "chair"
    CODE_EXTRA    = "extra"
    CODE_OTHER    = "other"

    code        = models.SlugField(
        max_length=30, unique=True,
        help_text="Stable machine code, e.g. 'lunch'. Never localized.",
    )
    name        = models.CharField(max_length=100, unique=True)
    is_planned  = models.BooleanField(
        default=False,
        verbose_name="Counts as planned downtime",
        help_text="If checked, time in this category is planned/scheduled "
                  "downtime (e.g. lunch); otherwise it is unplanned.",
    )
    is_active   = models.BooleanField(default=True)
    order       = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name        = "Event Category"
        verbose_name_plural = "Event Categories"
        ordering            = ["order", "name"]
        indexes             = [models.Index(fields=["code"])]

    def __str__(self):
        return self.name


class EventType(models.Model):
    """Admin-managed catalog of operational event kinds (Lunch, Chair Time,
    Meeting, Training, ...). Extending the catalog never requires a code
    change — just add a row here."""

    name        = models.CharField(max_length=100, unique=True)
    category    = models.ForeignKey(
        EventCategory, on_delete=models.PROTECT,
        related_name="event_types", null=True, blank=True,
        help_text="Canonical category this event type rolls up to for reporting.",
    )
    icon        = models.CharField(
        max_length=40, default="fa-circle-info",
        help_text="Font Awesome icon class suffix, e.g. 'fa-utensils'.",
    )
    color       = models.CharField(
        max_length=20, default="slate",
        help_text="Tailwind color name used for badges/cards, e.g. 'amber', 'blue'.",
    )
    requires_comment = models.BooleanField(
        default=False,
        verbose_name="Comment required",
        help_text="If checked, a comment is mandatory whenever this event type is used.",
    )
    is_active   = models.BooleanField(default=True)
    order       = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name        = "Event Type"
        verbose_name_plural = "Event Types"
        ordering            = ["order", "name"]

    def __str__(self):
        return self.name


class ExecutionEvent(models.Model):
    """A single operational event (Lunch, Chair Time, Meeting, ...) tied to
    one HourlyExecution row. Each event is its own record — never
    concatenated into a comment and never serialized as JSON."""

    SOURCE_MANUAL = "manual"
    SOURCE_BLOCK  = "block"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual entry"),
        (SOURCE_BLOCK,  "Auto-generated from Time Block"),
    ]

    execution        = models.ForeignKey(
        HourlyExecution, on_delete=models.CASCADE, related_name="events",
    )
    event_type       = models.ForeignKey(
        EventType, on_delete=models.PROTECT, related_name="executions",
    )
    duration_minutes = models.PositiveIntegerField()
    start_time       = models.TimeField(null=True, blank=True)
    end_time         = models.TimeField(null=True, blank=True)
    comment          = models.TextField(blank=True, default="")

    # ── Provenance ────────────────────────────────────────────────────────────
    # When an event is auto-generated from a planning Time Block, we keep a
    # FK back to that block. This makes auto-creation idempotent (re-saving a
    # block updates its one event instead of duplicating) and gives full
    # traceability from dashboard event → originating planned block.
    source           = models.CharField(
        max_length=10, choices=SOURCE_CHOICES, default=SOURCE_MANUAL,
        help_text="Whether this event was entered manually or generated "
                  "automatically from a planning Time Block.",
    )
    source_block     = models.OneToOneField(
        "planning.HourlyPlanBlock", null=True, blank=True,
        on_delete=models.CASCADE, related_name="generated_event",
        help_text="The Time Block that generated this event, if any.",
    )

    created_at       = models.DateTimeField(auto_now_add=True)
    # Once the user edits an auto-generated event, this becomes True so the
    # Time Block → Event sync will NOT overwrite their changes on re-save.
    # The block seeds the event once; after that, the execution record wins.
    user_modified    = models.BooleanField(
        default=False,
        help_text="True once a human edited this event; blocks the auto-sync "
                  "from a planning Time Block from overwriting it.",
    )
    created_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name        = "Execution Event"
        verbose_name_plural = "Execution Events"
        ordering            = ["created_at"]
        indexes             = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["source"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type.name} — {self.duration_minutes} min ({self.execution_id})"

    # ── Duration auto-calculation ─────────────────────────────────────────────
    @staticmethod
    def minutes_between(start, end):
        """Whole minutes from start to end (same day; wraps past midnight).
        Returns None when either bound is missing."""
        if not start or not end:
            return None
        import datetime as _dt
        base  = _dt.date.today()
        s     = _dt.datetime.combine(base, start)
        e     = _dt.datetime.combine(base, end)
        if e < s:                      # event crosses midnight
            e += _dt.timedelta(days=1)
        return int((e - s).total_seconds() // 60)

    def save(self, *args, **kwargs):
        # Duration = End - Start whenever both are given; the spec forbids
        # requiring manual duration entry when start/end are known.
        derived = self.minutes_between(self.start_time, self.end_time)
        if derived is not None:
            self.duration_minutes = derived
        super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        derived = self.minutes_between(self.start_time, self.end_time)
        effective_duration = derived if derived is not None else self.duration_minutes
        if effective_duration is not None and effective_duration < 0:
            errors["duration_minutes"] = "Duration cannot be negative."
        if self.event_type_id and self.event_type.requires_comment and not (self.comment or "").strip():
            errors["comment"] = f"A comment is required for '{self.event_type.name}' events."
        if errors:
            raise ValidationError(errors)