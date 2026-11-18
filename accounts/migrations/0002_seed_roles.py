"""Create every permission switch and the default User and Admin roles."""

from django.db import migrations

# Copied here (not imported) so this migration keeps working if the list changes.
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
USER_PERMS = ["view", "create_item", "create_ticket", "edit_ticket", "resolve_ticket", "reopen_ticket"]


def seed(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perms = {}
    for i, (code, name, description) in enumerate(PERMISSIONS):
        perms[code], _ = Permission.objects.update_or_create(
            code=code, defaults={"name": name, "description": description, "sort_order": i}
        )
    user_role, created = Role.objects.get_or_create(name="User", defaults={"description": "Everyday use during checks."})
    if created:
        user_role.permissions.set([perms[c] for c in USER_PERMS])
    admin_role, created = Role.objects.get_or_create(name="Admin", defaults={"description": "Full access."})
    if created:
        admin_role.permissions.set(perms.values())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
