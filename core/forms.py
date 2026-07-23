# core/forms.py

from django import forms
from .models import WorkCenter, SubProcess, SubProcessType, Shift

_input  = ("w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm "
           "focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none")
_select = _input + " bg-white"
_area   = _input + " resize-none"


# ─── Work Center ──────────────────────────────────────────────────────────────

class WorkCenterForm(forms.ModelForm):
    class Meta:
        model   = WorkCenter
        fields  = ["name", "description", "is_active"]
        widgets = {
            "name":        forms.TextInput(attrs={"class": _input, "placeholder": "Work center name"}),
            "description": forms.Textarea(attrs={"class": _area, "rows": 3,
                                                  "placeholder": "Optional description"}),
            "is_active":   forms.CheckboxInput(
                attrs={"class": "h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"}),
        }


# ─── Subprocess Type (Admin only) ─────────────────────────────────────────────

class SubProcessTypeForm(forms.ModelForm):
    class Meta:
        model   = SubProcessType
        fields  = ["name", "applies_to", "units_per_piece", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": _input,
                "placeholder": "e.g. Normal, Winding, Braze…",
            }),
            "applies_to": forms.Select(attrs={"class": _select}),
            "units_per_piece": forms.NumberInput(attrs={
                "class": _input,
                "min": 1,
                "placeholder": "1",
            }),
            "is_active": forms.CheckboxInput(
                attrs={"class": "h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"}),
        }
        labels = {
            "name":           "Type Name",
            "applies_to":     "Applies To",
            "units_per_piece":"Units per Piece",
            "is_active":      "Active",
        }
        help_texts = {
            "units_per_piece": "How many units make up 1 complete piece. "
                               "Example: if 3 units = 1 piece, enter 3.",
            "applies_to":      "Which production line does this subprocess type apply to?",
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs   = SubProcessType.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A subprocess type with this name already exists.")
        return name

    def clean_units_per_piece(self):
        val = self.cleaned_data.get("units_per_piece")
        if val is None or val < 1:
            raise forms.ValidationError("Units per piece must be at least 1.")
        return val


# ─── SubProcess ───────────────────────────────────────────────────────────────

class SubProcessForm(forms.ModelForm):
    class Meta:
        model   = SubProcess
        fields  = ["work_center", "name", "subprocess_type"]
        widgets = {
            "work_center":     forms.Select(attrs={"class": _select}),
            "name":            forms.TextInput(attrs={
                                   "class": _input,
                                   "placeholder": "Subprocess name",
                               }),
            "subprocess_type": forms.Select(attrs={"class": _select}),
        }
        labels = {
            "subprocess_type": "Subprocess Type",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active types in the dropdown
        self.fields["subprocess_type"].queryset = (
            SubProcessType.objects.filter(is_active=True).order_by("name")
        )
        self.fields["subprocess_type"].empty_label = "— Select a type —"
        self.fields["subprocess_type"].required = True


# ─── Shift ────────────────────────────────────────────────────────────────────

class ShiftForm(forms.ModelForm):

    days_of_week = forms.MultipleChoiceField(
        choices=[(0,'Monday'),(1,'Tuesday'),(2,'Wednesday'),(3,'Thursday'),
                 (4,'Friday'),(5,'Saturday'),(6,'Sunday')],
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Applicable Days",
    )

    class Meta:
        model  = Shift
        fields = ["name", "code", "start_time", "end_time", "is_active"]
        widgets = {
            "name":       forms.TextInput(attrs={
                              "class": _input,
                              "placeholder": "e.g. Morning, Afternoon, Night"}),
            "code":       forms.TextInput(attrs={
                              "class": _input,
                              "placeholder": "e.g. DAY, AFT, NGT",
                              "style": "text-transform:uppercase"}),
            "start_time": forms.TimeInput(attrs={"class": _input, "type": "time"}),
            "end_time":   forms.TimeInput(attrs={"class": _input, "type": "time"}),
            "is_active":  forms.CheckboxInput(attrs={
                              "class": "h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.days_of_week:
            self.initial['days_of_week'] = [str(d) for d in self.instance.days_of_week]

    def selected_day_ints(self):
        val = self['days_of_week'].value()
        if not val:
            return set()
        return {int(v) for v in val}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs   = Shift.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A shift with this name already exists.")
        return name

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        qs   = Shift.objects.filter(code__iexact=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A shift with this code already exists.")
        return code

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.days_of_week = sorted(
            int(d) for d in self.cleaned_data.get('days_of_week', [])
        )
        if commit:
            instance.save()
        return instance