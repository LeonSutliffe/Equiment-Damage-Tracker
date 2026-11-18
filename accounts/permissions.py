from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q


def require_perm(*codes):
    """Refuse the request unless the user's role has every listed permission.

    Checked on the server for every request, so hiding a button is never the
    only protection (architecture section 4).
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            for code in codes:
                if not request.user.can(code):
                    raise PermissionDenied(f"Your role does not have the '{code}' permission.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def admin_remains():
    """True if at least one active user has both manage_roles and manage_users."""
    from .models import User

    return (
        User.objects.filter(is_active=True, role__isnull=False)
        .annotate(
            admin_perms=Count(
                "role__permissions",
                filter=Q(role__permissions__code__in=["manage_roles", "manage_users"]),
                distinct=True,
            )
        )
        .filter(admin_perms=2)
        .exists()
    )


class LockoutError(Exception):
    """Raised inside a transaction to undo a change that would lock everyone out."""

    message = (
        "That change would leave no active user who can manage both users and roles, "
        "so nobody could fix it afterwards. It has not been saved."
    )
