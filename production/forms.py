# production/forms.py
# COPY-PASTE → hrxhr_project/production/forms.py

from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from core.limits import MAX_QUANTITY, check_headcount, check_quantity
from .models import HourlyExecution, LossReason, EventType, ExecutionEvent

_input   = ("w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm "
            "focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none")
_textarea = _input + " resize-none text-xs"
_input_sm = ("w-full rounded-md border border-gray-300 px-2 py-1.5 text-xs shadow-sm "
             "focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none")


class HourlyExecutionForm(forms.ModelForm):

    loss_reasons = forms.ModelMultipleChoiceField(
        queryset=LossReason.objects.all().order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Loss Reasons",
    )

    # ── Quantity fields — min_value=0 enforces no-negative rule ──────────────
    actual_quantity = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=MAX_QUANTITY,
        error_messages={
            "min_value": "Actual quantity cannot be negative. Please enter 0 or more.",
            "max_value": f"Actual quantity cannot be greater than {MAX_QUANTITY:,}.",
            "invalid":   "Enter a valid whole number for actual quantity.",
        },
        widget=forms.NumberInput(attrs={
            "class":       _input + " text-right",
            "min":         "0",
            "placeholder": "0",
            "oninput":     "validateNonNegative(this)",
        }),
    )

    scrap_quantity = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=MAX_QUANTITY,
        initial=0,
        error_messages={
            "min_value": "Scrap quantity cannot be negative. Please enter 0 or more.",
            "max_value": f"Scrap quantity cannot be greater than {MAX_QUANTITY:,}.",
            "invalid":   "Enter a valid whole number for scrap quantity.",
        },
        widget=forms.NumberInput(attrs={
            "class":       _input + " text-right",
            "min":         "0",
            "placeholder": "0",
            "oninput":     "validateNonNegative(this)",
        }),
    )

    class Meta:
        model   = HourlyExecution
        fields  = [
            "actual_quantity", "scrap_quantity",
            "actual_headcount", "headcount_comment",
            "comments", "scrap_comments", "over_comments",
            "ok_comments", "zero_comment",
        ]
        widgets = {
            "actual_headcount": forms.NumberInput(attrs={
                "class": ("w-20 rounded-lg border border-gray-300 px-2 py-1 text-sm "
                          "text-right shadow-sm focus:border-blue-500 "
                          "focus:ring-1 focus:ring-blue-500 focus:outline-none "
                          "actual-hc-input"),
                "min": 0, "placeholder": "—",
            }),
            "headcount_comment": forms.Textarea(attrs={
                "class": _textarea, "rows": 2,
                "placeholder": "Why did the headcount differ from the plan?",
            }),
            "comments": forms.Textarea(attrs={
                "class": _textarea, "rows": 2,
                "placeholder": "Explain why target was missed…",
            }),
            "scrap_comments": forms.Textarea(attrs={
                "class": _textarea, "rows": 2,
                "placeholder": "Describe the scrap generated…",
            }),
            "over_comments": forms.Textarea(attrs={
                "class": _textarea, "rows": 2,
                "placeholder": "Explain the overproduction…",
            }),
            "ok_comments": forms.Textarea(attrs={
                "class": _textarea, "rows": 2,
                "placeholder": "Add a satisfactory note…",
            }),
            "zero_comment": forms.Textarea(attrs={
                "class": _textarea, "rows": 2,
                "placeholder": "Optional: describe why no production occurred this hour…",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("comments", "scrap_comments", "over_comments",
                  "ok_comments", "zero_comment"):
            self.fields[f].required = False

    def clean_actual_headcount(self):
        # The "min" on the input is only a browser hint; enforce it here too.
        # 0 is allowed (nobody worked that hour), blank means "not captured".
        val = self.cleaned_data.get("actual_headcount")
        if val is not None:
            err = check_headcount(val, "Head count", minimum=0)
            if err:
                raise forms.ValidationError(err)
        return val

    def clean_actual_quantity(self):
        val = self.cleaned_data.get("actual_quantity")
        if val is None:
            return val
        if val < 0:
            raise forms.ValidationError(
                "Actual quantity cannot be negative. Please enter 0 or more."
            )
        return val

    def clean_scrap_quantity(self):
        val = self.cleaned_data.get("scrap_quantity")
        if val is None:
            return 0
        if val < 0:
            raise forms.ValidationError(
                "Scrap quantity cannot be negative. Please enter 0 or more."
            )
        return val

    def clean(self):
        cleaned = super().clean()
        actual  = cleaned.get("actual_quantity") or 0
        scrap   = cleaned.get("scrap_quantity")  or 0
        if scrap > actual:
            raise forms.ValidationError(
                f"Scrap ({scrap}) cannot exceed actual quantity ({actual})."
            )
        return cleaned


# ─── Operational Events ─────────────────────────────────────────────────────
# Fully independent from the situational comment fields above. Each event is
# validated and saved as its own ExecutionEvent row -- never merged into
# HourlyExecution.comments and never serialized as JSON.

class ExecutionEventForm(forms.ModelForm):

    class Meta:
        model  = ExecutionEvent
        fields = ["event_type", "duration_minutes", "comment"]
        widgets = {
            "event_type": forms.Select(attrs={"class": _input_sm}),
            "duration_minutes": forms.NumberInput(attrs={
                "class": _input_sm + " text-right", "min": "0", "placeholder": "min",
            }),
            "comment": forms.TextInput(attrs={
                "class": _input_sm, "placeholder": "Comment (optional)",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_type"].queryset    = EventType.objects.filter(is_active=True)
        self.fields["event_type"].empty_label = "Select event type..."
        self.fields["event_type"].required    = False
        self.fields["duration_minutes"].required = False
        self.fields["comment"].required = False

    def clean_duration_minutes(self):
        val = self.cleaned_data.get("duration_minutes")
        if val is not None and val < 0:
            raise forms.ValidationError("Duration cannot be negative.")
        return val

    def clean(self):
        cleaned    = super().clean()
        event_type = cleaned.get("event_type")
        duration   = cleaned.get("duration_minutes")
        comment    = (cleaned.get("comment") or "").strip()

        # An untouched extra row (nothing selected/entered) is simply
        # ignored rather than raising "this field is required" noise.
        is_blank = not event_type and duration in (None, "") and not comment
        if is_blank:
            if self.instance.pk:
                cleaned["DELETE"] = True
            return cleaned

        if not event_type:
            raise forms.ValidationError("Select an event type for this event.")
        if duration is None:
            raise forms.ValidationError(
                f"Enter a duration in minutes for '{event_type.name}'."
            )
        if duration < 0:
            raise forms.ValidationError("Duration cannot be negative.")
        if event_type.requires_comment and not comment:
            raise forms.ValidationError(
                f"A comment is required for '{event_type.name}' events."
            )
        return cleaned


class BaseExecutionEventFormSet(BaseInlineFormSet):
    """The events of one hour cannot add up to more than the hour itself.

    A typo such as 600 instead of 60 would otherwise inflate Downtime Real,
    the Pareto and every downtime card, while Runtime (floored at 0) hides it.
    The view sets `slot_minutes` (60, or less for a partial last slot of the
    shift) before validating; without it the check is skipped."""
    slot_minutes = None

    def clean(self):
        super().clean()
        limit = self.slot_minutes
        if not limit:
            return
        total = 0
        for form in self.forms:
            cd = getattr(form, "cleaned_data", None)
            if not cd or cd.get("DELETE"):
                continue
            minutes = cd.get("duration_minutes")
            if not minutes:
                continue
            total += minutes
            if total > limit:
                # Reported on the event that goes over, so it reaches the
                # same error list the single-event checks already use.
                form.add_error(
                    None,
                    f"The events of this hour add up to {total} min, but the hour "
                    f"only has {limit} min. Check the duration.")
                return


ExecutionEventFormSet = inlineformset_factory(
    HourlyExecution,
    ExecutionEvent,
    form=ExecutionEventForm,
    formset=BaseExecutionEventFormSet,
    extra=0,
    can_delete=True,
)