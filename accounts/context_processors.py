class _Perms:
    def __init__(self, user):
        self._user = user

    def __getattr__(self, code):
        return bool(self._user.is_authenticated and self._user.can(code))


def permissions(request):
    """Lets templates write {% if perms_ok.edit_ticket %} and {% if can_delete_permanently %}."""
    user = request.user
    permanent = bool(user.is_authenticated and user.allow_permanent_delete and user.can("delete_records"))
    return {"perms_ok": _Perms(user), "can_delete_permanently": permanent}
