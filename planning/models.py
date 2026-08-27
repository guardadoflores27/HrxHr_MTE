# planning/models.py
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

import datetime as dt
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from core.models import WorkCenter, SubProcess, Shift


class Model(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Model"
        ordering     = ["name"]


class DailyPlan(models.Model):
    date        = models.DateField()
    work_center = models.ForeignKey(WorkCenter, on_delete=models.CASCADE)
    subprocess  = models.ForeignKey(SubProcess, on_delete=models.CASCADE)
    headcount   = models.IntegerField()
    shift       = models.ForeignKey(
        Shift, on_delete=models.PROTECT, related_name="daily_plans",
        null=True, blank=True,
    )
    # Semantic operator for the whole shift (NOT an audit user). This is the
    # dimension behind 'Events per Operator' / 'Total Time by Operator'.
    # Individual hours may override it via HourlyPlan.operator.
    operator    = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="operated_daily_plans",
        help_text="Operator running this line for the shift.",
    )
    # Snapshot of the operator's display name, kept in sync on every save()
    # while `operator` is set. Survives user deletion (operator goes NULL, 
    # operator_name keeps the last known value) — same pattern as
    # created_by_name/updated_by_name below.
    operator_name = models.CharField(max_length=150, blank=True)

    # Audit — FK goes NULL on user delete; *_name snapshots survive deletion
    created_by      = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="plans_created",
    )
    created_by_name = models.CharField(max_length=150, blank=True)
    created_at      = models.DateTimeField(default=timezone.now)
    updated_by      = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="plans_updated",
    )
    updated_by_name = models.CharField(max_length=150, blank=True)
    updated_at      = models.DateTimeField(auto_now=True)

    @property
    def creator_display(self):
        return self.created_by.username if self.created_by else (self.created_by_name or "—")

    @property
    def updater_display(self):
        return self.updated_by.username if self.updated_by else (self.updated_by_name or "—")

    @property
    def operator_display(self):
        return self.operator.username if self.operator else (self.operator_name or "—")

    def save(self, *args, **kwargs):
        if self.operator_id:
            self.operator_name = self.operator.get_full_name() or self.operator.username
        super().save(*args, **kwargs)

    def __str__(self):
        shift_label = self.shift.name if self.shift else "—"
        return f"{self.work_center} - {self.subprocess} - {self.date} ({shift_label})"

    class Meta:
        verbose_name    = "Daily Plan"
        unique_together = [["date", "subprocess", "shift"]]
        indexes         = [
            models.Index(fields=["date"]),
            models.Index(fields=["work_center", "date"]),
            models.Index(fields=["shift", "date"]),
            models.Index(fields=["operator"]),
        ]


class HourlyPlan(models.Model):
    daily_plan       = models.ForeignKey(
        DailyPlan, on_delete=models.CASCADE, related_name="hourly_plans"
    )
    hour             = models.TimeField()
    model            = models.ForeignKey(Model, on_delete=models.CASCADE)
    planned_quantity = models.IntegerField()
    headcount        = models.IntegerField(
        null=True, blank=True,
        help_text="Per-hour headcount override",
    )
    is_overtime      = models.BooleanField(default=False)
    comments         = models.TextField(blank=True, default="")
    # Optional per-hour operator override; falls back to the shift operator.
    operator         = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="operated_hours",
        help_text="Overrides the shift operator for this hour only.",
    )
    # Same survives-deletion snapshot pattern as DailyPlan.operator_name.
    operator_name    = models.CharField(max_length=150, blank=True)

    @property
    def operator_display(self):
        return self.operator.username if self.operator else (self.operator_name or "—")

    def save(self, *args, **kwargs):
        if self.operator_id:
            self.operator_name = self.operator.get_full_name() or self.operator.username
        super().save(*args, **kwargs)

    def effective_headcount(self):
        return self.headcount if self.headcount is not None else self.daily_plan.headcount

    @property
    def effective_operator(self):
        """Per-hour operator if set, otherwise the shift-level operator."""
        return self.operator or self.daily_plan.operator

    @property
    def effective_operator_display(self):
        """Same fallback as effective_operator, but survives user deletion."""
        return self.operator_display if self.operator_id else self.daily_plan.operator_display

    @property
    def hour_end(self):
        h_dt = dt.datetime.combine(dt.date.today(), self.hour)
        return (h_dt + dt.timedelta(hours=1)).time()

    def __str__(self):
        return f"{self.daily_plan} | {self.hour} | {self.model.name}"

    class Meta:
        verbose_name = "Hourly Plan"
        ordering     = ["hour"]


# ─── Operational Time Blocks ──────────────────────────────────────────────────

class HourlyPlanBlock(models.Model):
    BLOCK_LUNCH   = "lunch"
    BLOCK_PREOP   = "preop"
    BLOCK_WORKFIN = "workfin"
    BLOCK_CHAIR   = "chair"
    BLOCK_EXTRA   = "extra"

    BLOCK_TYPES = [
        (BLOCK_LUNCH,   "Lunch Break"),
        (BLOCK_PREOP,   "Operation Preparation"),
        (BLOCK_WORKFIN, "Work Finalization"),
        (BLOCK_CHAIR,   "Chair Time"),
        (BLOCK_EXTRA,   "Extra Reason"),
    ]

    daily_plan = models.ForeignKey(DailyPlan, on_delete=models.CASCADE, related_name="blocks")
    slot_time  = models.TimeField(help_text="Slot start time (HH:MM)")
    block_type = models.CharField(max_length=20, choices=BLOCK_TYPES)
    minutes    = models.IntegerField(default=0)
    reason     = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def label(self):
        if self.block_type == self.BLOCK_EXTRA and self.reason:
            return self.reason
        return self.get_block_type_display()

    def category(self):
        """Machine-readable category code for dashboard filtering.
        Always one of: lunch / preop / workfin / chair / extra —
        independent of the human-readable label or any free text.
        This code maps 1:1 to production.EventCategory.code."""
        return self.block_type

    def __str__(self):
        return f"{self.label()} · {self.minutes}min @ {self.slot_time}"

    class Meta:
        verbose_name = "Hourly Plan Block"
        ordering     = ["slot_time", "created_at"]
        indexes      = [
            models.Index(fields=["daily_plan", "slot_time"]),
            models.Index(fields=["block_type"]),
        ]


# ─── Headcount Audit ──────────────────────────────────────────────────────────

class HeadcountAudit(models.Model):
    daily_plan       = models.ForeignKey(
        DailyPlan, on_delete=models.CASCADE, related_name="hc_audits"
    )
    previous_value   = models.IntegerField()
    new_value        = models.IntegerField()
    comment          = models.TextField()
    modified_by      = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    modified_by_name = models.CharField(max_length=150, blank=True)
    modified_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"HC {self.previous_value}→{self.new_value} by {self.modified_by_name}"

    class Meta:
        verbose_name = "Headcount Audit"
        ordering     = ["-modified_at"]