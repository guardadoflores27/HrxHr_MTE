# users/forms.py

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
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

    class Meta:
        model  = User
        fields = ["username", "first_name", "last_name", "email",
                  "password1", "password2", "role"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": _input})
        self.fields["password1"].widget.attrs.update({"class": _input})
        self.fields["password2"].widget.attrs.update({"class": _input})

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data.get("first_name", "")
        user.last_name  = self.cleaned_data.get("last_name",  "")
        user.email      = self.cleaned_data.get("email",      "")
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data["role"]
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