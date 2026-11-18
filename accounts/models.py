from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils import timezone

# Every permission is one on/off switch (architecture section 4).
PERMISSIONS = [
    ("view", "View", "Search, view items, tickets, photos and field history."),
    ("create_item", "Create item", "Create new items."),
    ("edit_item", "Edit item", "Change an item's type, barcode or serial number."),
    ("create_ticket", "Create ticket", "Start new tickets."),
    ("edit_ticket", "Edit ticket", "Change ticket fields and add photos."),
    ("resolve_ticket", "Resolve ticket", "Set a ticket to Resolved."),
    ("reopen_ticket", "Reopen ticket", "Reopen a resolved ticket."),
    ("remove_photo", "Remove photo", "Hide a photo from a ticket (it is kept and the removal is logged)."),
    ("manage_item_types", "Manage item types", "Add, rename and deactivate item types."),
    ("manage_checks", "Manage checks", "Start and close yearly checks."),
    ("export", "Export", "Export lists to CSV and print ticket sheets."),
    ("manage_users", "Manage users", "Create and deactivate users, reset passwords, change a user's role."),
    ("manage_roles", "Manage roles", "Create roles and change which permissions each role has."),
]
PERMISSION_CODES = [code for code, _, _ in PERMISSIONS]

DEFAULT_ROLES = {
    "User": ["view", "create_item", "create_ticket", "edit_ticket", "resolve_ticket", "reopen_ticket"],
    "Admin": PERMISSION_CODES,
}


class Permission(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "code"]

    def __str__(self):
        return self.name


class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.ManyToManyField(Permission, blank=True, related_name="roles")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def permission_codes(self):
        return set(self.permissions.values_list("code", flat=True))


class TrackerUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # `manage.py createsuperuser` gives the new account the Admin role.
        if not extra_fields.get("role"):
            extra_fields["role"] = Role.objects.filter(name="Admin").first()
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """A person who logs in. Access comes only from their role."""

    display_name = models.CharField(max_length=150, blank=True)
    role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.PROTECT, related_name="users")
    failed_logins = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    objects = TrackerUserManager()

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return self.display_name or self.username

    @property
    def label(self):
        return self.display_name or self.username

    def perm_codes(self):
        # Cached for the request; roles take effect on the next page load.
        if not hasattr(self, "_perm_codes"):
            if not self.is_active or self.role_id is None:
                self._perm_codes = set()
            else:
                self._perm_codes = self.role.permission_codes()
        return self._perm_codes

    def can(self, code):
        return code in self.perm_codes()

    def is_locked(self):
        return self.locked_until is not None and self.locked_until > timezone.now()


class PermissionChange(models.Model):
    """Audit trail of role and user-role changes, visible to admins."""

    changed_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    target = models.CharField(max_length=150)
    change = models.CharField(max_length=500)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.target}: {self.change}"
