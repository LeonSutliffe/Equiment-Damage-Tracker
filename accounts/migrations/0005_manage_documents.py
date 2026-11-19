"""Add the Manage documents permission and give it to Admin."""

from django.db import migrations


def add(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")
    perm, _ = Permission.objects.update_or_create(
        code="manage_documents",
        defaults={
            "name": "Manage documents",
            "description": "Add manuals and other documents to item types and items, and remove them.",
            "sort_order": Permission.objects.count(),
        },
    )
    for role in Role.objects.filter(name="Admin"):
        role.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_more_permissions")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
