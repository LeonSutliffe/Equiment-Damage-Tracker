class _Perms:
    def __init__(self, user):
        self._user = user

    def __getattr__(self, code):
        return bool(self._user.is_authenticated and self._user.can(code))


def permissions(request):
    """Lets templates write {% if perms_ok.edit_ticket %}."""
    return {"perms_ok": _Perms(request.user)}
