# core/models.py
# ─────────────────────────────────────────────────────────────────────────────

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class AuditMixin(models.Model):
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name="Created by")
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name="Updated by")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True


class WorkCenter(AuditMixin, models.Model):
    name        = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name        = "Work Center"
        verbose_name_plural = "Work Centers"


# ─── SubProcessType ───────────────────────────────────────────────────────────

class SubProcessType(models.Model):
    """
    Configurable subprocess type catalog — managed by Admin only.
    Replaces the hardcoded PROCESS_TYPES / CONVERSION_FACTORS on SubProcess.
    """

    APPLIES_REACTORES         = "reactores"
    APPLIES_REACTORES_FILTROS = "reactores_filtros"

    APPLIES_CHOICES = [
        (APPLIES_REACTORES,         "Reactores"),
        (APPLIES_REACTORES_FILTROS, "Reactores-Filtros"),
    ]

    name           = models.CharField(max_length=100, unique=True,
                                      verbose_name="Nombre del tipo")
    applies_to     = models.CharField(max_length=30, choices=APPLIES_CHOICES,
                                      verbose_name="Aplica para")
    units_per_piece = models.PositiveIntegerField(
        default=1,
        verbose_name="Contador de unidades por pieza",
        help_text="Cuántas unidades se necesitan para completar 1 pieza. "
                  "Ej: si 3 unidades = 1 pieza, escribe 3.",
    )
    is_active      = models.BooleanField(default=True, verbose_name="Activo")
    created_at     = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.name} ({self.get_applies_to_display()}) — {self.units_per_piece}u/pc"

    @property
    def conversion_label(self):
        if self.units_per_piece == 1:
            return "1 piece = 1 unit"
        return f"1 piece = {self.units_per_piece} units"

    class Meta:
        verbose_name        = "Subprocess Type"
        verbose_name_plural = "Subprocess Types"
        ordering            = ["name"]


# ─── SubProcess ───────────────────────────────────────────────────────────────

class SubProcess(AuditMixin, models.Model):
    work_center      = models.ForeignKey(WorkCenter, on_delete=models.CASCADE)
    name             = models.CharField(max_length=100)
    subprocess_type  = models.ForeignKey(
        SubProcessType,
        on_delete=models.PROTECT,
        related_name="subprocesses",
        verbose_name="Tipo de subprocess",
        null=True,   # temporarily nullable during migration
        blank=True,
    )

    @property
    def conversion_factor(self):
        """Units needed per piece — comes from the linked SubProcessType."""
        if self.subprocess_type_id:
            return self.subprocess_type.units_per_piece
        return 1

    @property
    def conversion_label(self):
        if self.conversion_factor == 1:
            return "1 piece = 1 unit"
        return f"1 piece = {self.conversion_factor} units"

    def __str__(self):
        return f"{self.work_center.name} - {self.name}"

    class Meta:
        verbose_name        = "Sub Process"
        verbose_name_plural = "Sub Processes"


# ─── Shift ───────────────────────────────────────────────────────────────────

class Shift(models.Model):
    DAYS_OF_WEEK = [
        (0, 'Monday'),   (1, 'Tuesday'),  (2, 'Wednesday'),
        (3, 'Thursday'), (4, 'Friday'),   (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    name       = models.CharField(max_length=100, unique=True)
    code       = models.CharField(max_length=20, unique=True,
                                  help_text="Short identifier, e.g. DAY, AFT, NGT")
    start_time = models.TimeField()
    end_time   = models.TimeField()
    is_active  = models.BooleanField(default=True)
    days_of_week = models.JSONField(
        default=list, blank=True,
        help_text="Días de la semana: 0=Lunes, 1=Martes … 6=Domingo",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def crosses_midnight(self):
        return self.end_time < self.start_time

    @property
    def duration_display(self):
        s = self.start_time.strftime("%I:%M %p").lstrip("0")
        e = self.end_time.strftime("%I:%M %p").lstrip("0")
        return f"{s} – {e}"

    @property
    def days_display(self):
        short = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        return [short[d] for d in sorted(self.days_of_week or [])]

    @property
    def is_weekend_shift(self):
        return bool(set(self.days_of_week or []) & {5, 6})

    class Meta:
        verbose_name        = "Shift"
        verbose_name_plural = "Shifts"
        ordering            = ["start_time", "name"]