"""Add the Write off item, Bulk edit tickets and View audit log permissions, and give them to Admin."""

from django.db import migrations

NEW = [
    ("write_off_item", "Write off item", "Write off (dispose of) an item, or put it back in use. Its history is kept."),
    ("bulk_edit_tickets", "Bulk edit tickets", "Change the status or severity of many tickets at once, or comment on them all."),
    ("view_audit_log", "View audit log", "See who logged in and what everyone changed."),
]


def add(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    start = Permission.objects.count()
    for i, (code, name, description) in enumerate(NEW):
        perm, _ = Permission.objects.update_or_create(
            code=code, defaults={"name": name, "description": description, "sort_order": start + i}
        )
        for role in Role.objects.filter(name="Admin"):
            role.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_auditevent")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
