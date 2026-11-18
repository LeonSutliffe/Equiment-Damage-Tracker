from django.test import TestCase, override_settings
from django.urls import reverse

from .models import PermissionChange, Permission, Role, User


@override_settings(SECURE_SSL_REDIRECT=False, LOGIN_MAX_FAILURES=3)
class AccountTests(TestCase):
    def setUp(self):
        self.admin_role = Role.objects.get(name="Admin")
        self.user_role = Role.objects.get(name="User")
        self.admin = User.objects.create_user("leon", password="pw-123456!", role=self.admin_role)
        self.user = User.objects.create_user("jsmith", password="pw-123456!", role=self.user_role)

    def test_default_roles(self):
        self.assertEqual(len(self.admin_role.permission_codes()), 13)
        self.assertEqual(
            self.user_role.permission_codes(),
            {"view", "create_item", "create_ticket", "edit_ticket", "resolve_ticket", "reopen_ticket"},
        )

    def test_login_and_lockout(self):
        r = self.client.post(reverse("login"), {"username": "JSMITH", "password": "pw-123456!"})
        self.assertRedirects(r, reverse("home"))
        self.client.logout()
        for _ in range(3):
            self.client.post(reverse("login"), {"username": "jsmith", "password": "wrong"})
        r = self.client.post(reverse("login"), {"username": "jsmith", "password": "pw-123456!"})
        self.assertContains(r, "locked")

    def test_user_cannot_reach_admin_screens(self):
        self.client.force_login(self.user)
        for name in ("user_list", "role_list", "user_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_role_change_is_logged_and_takes_effect(self):
        self.client.force_login(self.admin)
        perms = list(self.user_role.permissions.values_list("pk", flat=True)) + [Permission.objects.get(code="edit_item").pk]
        self.client.post(reverse("role_edit", args=[self.user_role.pk]), {"name": "User", "description": "", "permissions": perms})
        self.assertTrue(PermissionChange.objects.filter(change="added edit_item").exists())
        self.assertTrue(User.objects.get(pk=self.user.pk).can("edit_item"))

    def test_cannot_lock_everyone_out(self):
        self.client.force_login(self.admin)
        # Removing manage_roles from the only admin role is refused.
        keep = list(self.admin_role.permissions.exclude(code="manage_roles").values_list("pk", flat=True))
        self.client.post(reverse("role_edit", args=[self.admin_role.pk]), {"name": "Admin", "permissions": keep})
        self.assertIn("manage_roles", Role.objects.get(pk=self.admin_role.pk).permission_codes())
        # Demoting the only admin is refused.
        self.client.post(reverse("user_edit", args=[self.admin.pk]), {"display_name": "", "role": self.user_role.pk, "is_active": "on"})
        self.assertEqual(User.objects.get(pk=self.admin.pk).role, self.admin_role)
        # With a second admin it is allowed (any user can be given admin rights).
        self.client.post(reverse("user_edit", args=[self.user.pk]), {"display_name": "", "role": self.admin_role.pk, "is_active": "on"})
        self.client.post(reverse("user_edit", args=[self.admin.pk]), {"display_name": "", "role": self.user_role.pk, "is_active": "on"})
        self.assertEqual(User.objects.get(pk=self.admin.pk).role, self.user_role)

    def test_create_user(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("user_create"), {
            "username": "new", "display_name": "N. Ew", "role": self.user_role.pk,
            "password1": "Ladder-check-2026", "password2": "Ladder-check-2026",
        })
        self.assertRedirects(r, reverse("user_list"))
        self.assertTrue(User.objects.get(username="new").check_password("Ladder-check-2026"))

    def test_createsuperuser_gets_admin_role(self):
        u = User.objects.create_superuser("boss", password="pw-123456!")
        self.assertEqual(u.role, self.admin_role)
