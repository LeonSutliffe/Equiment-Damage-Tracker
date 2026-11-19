"""Add the Delete records permission and give it to Admin."""

from django.db import migrations


def add(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perm, _ = Permission.objects.update_or_create(
        code="delete_records",
        defaults={
            "name": "Delete records",
            "description": "Remove comments (shown in history). With 'Allow permanent deletions' switched on in their "
                           "own Settings, permanently delete tickets, items, comments, photos and documents "
                           "(recorded only in the audit log).",
            "sort_order": Permission.objects.count(),
        },
    )
    for role in Role.objects.filter(name="Admin"):
        role.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0007_allow_permanent_delete")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
