from django import forms
from django.conf import settings
from django.contrib.auth import authenticate, password_validation
from django.utils import timezone

from .models import Permission, Role, User


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autofocus": True, "autocapitalize": "none", "autocomplete": "username"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        username = self.cleaned_data.get("username", "").strip()
        password = self.cleaned_data.get("password", "")
        if not username or not password:
            return self.cleaned_data
        account = User.objects.filter(username__iexact=username).first()
        if account and account.is_locked():
            raise forms.ValidationError(
                "This account is locked after too many wrong passwords. Try again later or ask an admin."
            )
        user = authenticate(self.request, username=account.username if account else username, password=password)
        if user is None:
            if account:
                account.failed_logins += 1
                if account.failed_logins >= settings.LOGIN_MAX_FAILURES:
                    account.locked_until = timezone.now() + timezone.timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                    account.failed_logins = 0
                account.save(update_fields=["failed_logins", "locked_until"])
            raise forms.ValidationError("Wrong username or password.")
        if user.failed_logins or user.locked_until:
            user.failed_logins = 0
            user.locked_until = None
            user.save(update_fields=["failed_logins", "locked_until"])
        self.user = user
        return self.cleaned_data


class _PasswordMixin:
    def _check_password(self, user):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p1 != p2:
            self.add_error("password2", "The two passwords don't match.")
        elif p1:
            try:
                password_validation.validate_password(p1, user)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)


class UserCreateForm(_PasswordMixin, forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repeat password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = User
        fields = ["username", "display_name", "role"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].required = True
        self.fields["display_name"].help_text = "Shown in history, e.g. J. Smith"

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("That username is already taken.")
        return username

    def clean(self):
        super().clean()
        self._check_password(User(username=self.cleaned_data.get("username", ""), display_name=self.cleaned_data.get("display_name", "")))
        return self.cleaned_data


class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name", "role", "is_active"]
        labels = {"is_active": "Active (can log in)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].required = True


class PasswordResetForm(_PasswordMixin, forms.Form):
    password1 = forms.CharField(label="New password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repeat new password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        self._check_password(self.user)
        return self.cleaned_data


class RoleForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all(), widget=forms.CheckboxSelectMultiple, required=False
    )

    class Meta:
        model = Role
        fields = ["name", "description", "permissions"]
