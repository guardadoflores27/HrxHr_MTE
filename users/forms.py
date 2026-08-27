# users/forms.py

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import password_validation
from .models import UserProfile

_input  = ("w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm "
           "focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none")
_select = _input + " bg-white"


class CreateUserForm(UserCreationForm):
    first_name = forms.CharField(max_length=50, required=False,
                                 widget=forms.TextInput(attrs={"class": _input}))
    last_name  = forms.CharField(max_length=50, required=False,
                                 widget=forms.TextInput(attrs={"class": _input}))
    email      = forms.EmailField(required=False,
                                  widget=forms.EmailInput(attrs={"class": _input}))
    role       = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES,
                                   widget=forms.Select(attrs={"class": _select}))
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": _input, "type": "date"}),
    )
    employee_number = forms.CharField(
        max_length=20, required=False,
        widget=forms.TextInput(attrs={"class": _input}),
        help_text="Used to generate default password (Name + Employee Number).",
    )

    class Meta:
        model  = User
        fields = ["username", "first_name", "last_name", "email",
                  "password1", "password2", "role"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": _input})
        self.fields["password1"].widget.attrs.update({"class": _input})
        self.fields["password2"].widget.attrs.update({"class": _input})
        # Password is now OPTIONAL: leave both blank to auto-generate the
        # default "Name + Employee Number" password. Admin can still type
        # a password manually if preferred.
        self.fields["password1"].required = False
        self.fields["password2"].required = False
        self.fields["password1"].help_text = (
            "Leave both password fields blank to auto-generate the default "
            "password from the Employee Number instead."
        )

    def clean_employee_number(self):
        value = (self.cleaned_data.get("employee_number") or "").strip()
        if value and UserProfile.objects.filter(employee_number=value).exists():
            raise forms.ValidationError("This Employee Number is already assigned to another user.")
        return value

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")

        if not password1 and not password2:
            # Both blank → auto-generate in save(). Skip Django's built-in
            # validators here on purpose: the business-mandated formula
            # (Name + Employee Number) is intentionally simple and would
            # fail UserAttributeSimilarityValidator (it's built from the
            # user's own name), which is fine — that trade-off was a
            # deliberate decision, not an oversight.
            return password2

        if password1 != password2:
            raise forms.ValidationError(
                self.error_messages["password_mismatch"], code="password_mismatch",
            )
        # A manually-typed password still goes through Django's normal
        # validation (length, similarity to username, common passwords...).
        self.instance.username = self.cleaned_data.get("username")
        password_validation.validate_password(password2, self.instance)
        return password2

    def clean(self):
        cleaned = super().clean()
        has_manual_password = cleaned.get("password1") and cleaned.get("password2")
        employee_number = (cleaned.get("employee_number") or "").strip()
        if not has_manual_password and not employee_number:
            raise forms.ValidationError(
                "Enter a password manually, or provide an Employee Number so "
                "a default password can be generated."
            )
        return cleaned

    @staticmethod
    def _default_password(user, employee_number):
        """
        Default password formula: Name + Employee Number (e.g. "Juan4521").
        Intentionally simple/predictable per that business decision —
        see clean_password2() for why it skips validation.
        """
        name_part = (user.first_name or user.username).strip().replace(" ", "")
        return f"{name_part}{employee_number}"

    def save(self, commit=True):
        user = super().save(commit=False)  # UserCreationForm already ran set_password(password1)
        user.first_name = self.cleaned_data.get("first_name", "")
        user.last_name  = self.cleaned_data.get("last_name",  "")
        user.email      = self.cleaned_data.get("email",      "")

        employee_number = (self.cleaned_data.get("employee_number") or "").strip()

        # `generated_password` is read by the view to show the admin the
        # plaintext password once, right after creation (it's hashed from
        # here on — this is the only moment it's visible).
        self.generated_password = None
        if not self.cleaned_data.get("password1"):
            self.generated_password = self._default_password(user, employee_number)
            user.set_password(self.generated_password)

        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role            = self.cleaned_data["role"]
            profile.date_of_birth   = self.cleaned_data.get("date_of_birth")
            profile.employee_number = employee_number or None
            profile.save()
        return user


class EditUserForm(forms.Form):
    """
    Simple form to change only the user's role.
    Using plain Form (not ModelForm) so that no User model fields
    are required — the template only needs to render the role selector.
    """
    role = forms.ChoiceField(
        choices=UserProfile.ROLE_CHOICES,
        widget=forms.Select(attrs={"class": _select}),
        label="Role",
    )

    def __init__(self, *args, **kwargs):
        # Accept `instance` kwarg (the User object) for compatibility
        # with the existing view that passes instance=target
        self._user = kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        # Pre-select the user's current role when rendering the form
        if self._user and hasattr(self._user, "profile"):
            self.fields["role"].initial = self._user.profile.role

    def save(self, commit=True):
        """Save the selected role to the user's profile."""
        if self._user and commit:
            profile, _ = UserProfile.objects.get_or_create(user=self._user)
            profile.role = self.cleaned_data["role"]
            profile.save()
        return self._user