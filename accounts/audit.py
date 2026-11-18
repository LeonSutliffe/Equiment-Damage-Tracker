"""Write lines to the audit log (who logged in, and who changed what)."""

import logging

log = logging.getLogger(__name__)


def client_ip(request):
    if request is None:
        return ""
    ip = request.META.get("REMOTE_ADDR", "")
    # Caddy runs on the same PC and passes the real address on.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded and ip in ("127.0.0.1", "::1"):
        ip = forwarded.split(",")[0].strip()
    return ip[:45]


def record(request, kind, text, link="", user=None, username=None):
    """Add an audit line. Never lets a logging problem break the user's action."""
    from .models import AuditEvent

    if user is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        user = request.user
    try:
        AuditEvent.objects.create(
            user=user, username=(username if username is not None else (user.username if user else ""))[:150],
            kind=kind, text=str(text)[:1000], link=link[:200], ip=client_ip(request),
        )
    except Exception:
        log.exception("Couldn't write audit event")
