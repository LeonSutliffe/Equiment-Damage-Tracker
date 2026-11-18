from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver

from .audit import record


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    record(request, "login", "Logged in", user=user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        record(request, "logout", "Logged out", user=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    from .models import User

    name = (credentials or {}).get("username", "")
    account = User.objects.filter(username__iexact=name).first() if name else None
    text = "Wrong password" if account else "Unknown username"
    record(request, "login_failed", text, user=account, username=name)
