# planning/forms.py
# ─────────────────────────────────────────────────────────────────────────────
# COPY-PASTE → hrxhr_project/planning/forms.py
# ─────────────────────────────────────────────────────────────────────────────

from django import forms
from .models import DailyPlan, HourlyPlan
from core.models import Shift

_input  = ("w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm "
           "focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none")
_select = _input + " bg-white"
_area   = _input + " resize-none"


# ─── Daily Plan ───────────────────────────────────────────────────────────────

class DailyPlanForm(forms.ModelForm):

    class Meta:
        model   = DailyPlan
        fields  = ["date", "work_center", "subprocess", "headcount", "shift"]
        widgets = {
            "date":        forms.DateInput(attrs={"class": _input, "type": "date"}),
            "work_center": forms.Select(attrs={"class": _select}),
            "subprocess":  forms.Select(attrs={"class": _select}),
            "headcount":   forms.NumberInput(attrs={"class": _input, "min": 1}),
            "shift":       forms.Select(attrs={"class": _select, "id": "id_shift"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["shift"].queryset    = Shift.objects.filter(is_active=True).order_by("start_time")
        self.fields["shift"].empty_label = "— Select a shift —"
        self.fields["shift"].required    = True

    def clean(self):
        cleaned    = super().clean()
        date       = cleaned.get("date")
        subprocess = cleaned.get("subprocess")
        shift      = cleaned.get("shift")

        # ── Duplicate plan check ──────────────────────────────────────────────
        if date and subprocess and shift:
            qs = DailyPlan.objects.filter(date=date, subprocess=subprocess, shift=shift)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f"A plan for '{subprocess.name}' on shift '{shift.name}' already exists "
                    f"for {date}."
                )

        # ── Shift applies to this weekday ─────────────────────────────────────
        if date and shift and shift.days_of_week:
            day_of_week = date.weekday()   # 0=Mon … 6=Sun
            day_names   = ["Lunes", "Martes", "Miércoles", "Jueves",
                           "Viernes", "Sábado", "Domingo"]
            if day_of_week not in shift.days_of_week:
                dias = ", ".join(day_names[d] for d in sorted(shift.days_of_week))
                raise forms.ValidationError(
                    f"El turno '{shift.name}' no aplica para {day_names[day_of_week]}. "
                    f"Días configurados: {dias}."
                )

        return cleaned


# ─── Hourly Plan (fallback form — main input is now AJAX) ─────────────────────

class HourlyPlanForm(forms.ModelForm):
    is_overtime = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "id_is_overtime"}),
    )

    class Meta:
        model   = HourlyPlan
        fields  = ["hour", "model", "planned_quantity", "headcount", "comments", "is_overtime"]
        widgets = {
            "hour":             forms.TimeInput(
                attrs={"class": _input, "type": "time", "id": "id_hour"}),
            "model":            forms.Select(attrs={"class": _select}),
            "planned_quantity": forms.NumberInput(
                attrs={"class": _input, "min": 0, "placeholder": "0"}),
            "headcount":        forms.NumberInput(
                attrs={"class": _input, "min": 1, "placeholder": "HC override"}),
            "comments":         forms.Textarea(
                attrs={"class": _area, "rows": 2, "placeholder": "Comentarios opcionales…"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["headcount"].required = False
        self.fields["comments"].required  = False


# ─── Headcount edit (used in headcount modal) ─────────────────────────────────

class HeadcountEditForm(forms.Form):
    new_headcount = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={"class": _input, "min": 1}),
        label="Nuevo headcount",
    )
    comment = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={
            "class": _area, "rows": 3,
            "placeholder": "Razón del cambio (obligatorio)…",
        }),
        label="Comentario de ajuste",
    )