import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import Role, User

from .models import FieldChange, Item, ItemChange, ItemType, Photo, Ticket
from .services import ConflictError, create_ticket, update_ticket

TMP_PHOTOS = tempfile.mkdtemp()


def jpeg(name="p.jpg", size=(2400, 1200)):
    buf = BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


@override_settings(PHOTOS_DIR=Path(TMP_PHOTOS), SECURE_SSL_REDIRECT=False)
class TrackerTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_PHOTOS, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user("jsmith", password="pw-123456!", display_name="J. Smith", role=Role.objects.get(name="User"))
        self.admin = User.objects.create_user("leon", password="pw-123456!", role=Role.objects.get(name="Admin"))
        self.ladder = ItemType.objects.create(name="Step ladder 3m")
        self.item = Item.objects.create(item_type=self.ladder, barcode="501234567", serial_number="LD-0087")
        self.client.force_login(self.user)

    def new_ticket(self, **kw):
        data = {"fault_type": "safety", "severity": "high", "fault_description": "Rung cracked"} | kw
        return create_ticket(self.item, self.user, data)

    # ---- search
    def test_search_barcode_opens_item(self):
        r = self.client.get(reverse("home"), {"q": "501234567"})
        self.assertRedirects(r, reverse("item_detail", args=[self.item.pk]))

    def test_search_serial_case_insensitive(self):
        r = self.client.get(reverse("home"), {"q": "ld-0087"})
        self.assertRedirects(r, reverse("item_detail", args=[self.item.pk]))

    def test_search_ticket_number_forms(self):
        t = self.new_ticket()
        for q in (t.code, "t1", "T 1", "1"):
            r = self.client.get(reverse("home"), {"q": q})
            self.assertRedirects(r, reverse("ticket_detail", args=[t.number]), msg_prefix=q)

    def test_search_partial_lists_items(self):
        Item.objects.create(item_type=self.ladder, barcode="501234999", serial_number="LD-0099")
        r = self.client.get(reverse("home"), {"q": "5012"})
        self.assertContains(r, "2 matches")

    def test_search_nothing_offers_create(self):
        r = self.client.get(reverse("home"), {"q": "NEW-1"})
        self.assertContains(r, reverse("item_create") + "?serial_number=NEW-1")

    # ---- items
    def test_create_item_goes_to_new_ticket_and_rejects_duplicates(self):
        r = self.client.post(reverse("item_create"), {"item_type": self.ladder.pk, "barcode": "111", "serial_number": "S-1"})
        item = Item.objects.get(barcode="111")
        self.assertRedirects(r, reverse("ticket_create", args=[item.pk]))
        self.assertEqual(ItemChange.objects.filter(item=item).count(), 3)
        r = self.client.post(reverse("item_create"), {"item_type": self.ladder.pk, "barcode": "111", "serial_number": "ld-0087"})
        self.assertContains(r, "already used")
        self.assertEqual(Item.objects.count(), 2)

    def test_user_role_cannot_edit_item(self):
        r = self.client.get(reverse("item_edit", args=[self.item.pk]))
        self.assertEqual(r.status_code, 403)

    def test_item_edit_is_logged(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("item_edit", args=[self.item.pk]), {"item_type": self.ladder.pk, "barcode": "999", "serial_number": "LD-0087"})
        change = ItemChange.objects.get(item=self.item, field="barcode")
        self.assertEqual((change.old_value, change.new_value), ("501234567", "999"))

    # ---- tickets
    def test_ticket_numbers_and_created_history(self):
        t1, t2 = self.new_ticket(), self.new_ticket()
        self.assertEqual((t1.code, t2.code), ("T-00001", "T-00002"))
        self.assertEqual(t1.status, "open")
        fields = set(FieldChange.objects.filter(ticket=t1, note="created").values_list("field", flat=True))
        self.assertEqual(fields, {"status", "fault_type", "severity", "fault_description"})

    def test_create_ticket_via_form_with_photo(self):
        r = self.client.post(
            reverse("ticket_create", args=[self.item.pk]),
            {"fault_type": "cosmetic", "severity": "low", "fault_description": "Scratch", "photos": [jpeg()]},
        )
        t = Ticket.objects.get()
        self.assertRedirects(r, reverse("ticket_detail", args=[t.number]))
        photo = Photo.objects.get(ticket=t)
        with Image.open(f"{TMP_PHOTOS}/{photo.file_name}") as img:
            self.assertEqual(max(img.size), 2000)
        r = self.client.get(reverse("photo_thumb", args=[photo.pk]))
        self.assertEqual(r.status_code, 200)

    def test_rejects_non_image(self):
        bad = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
        r = self.client.post(reverse("ticket_create", args=[self.item.pk]), {"fault_type": "cosmetic", "severity": "low", "photos": [bad]})
        self.assertContains(r, "not a photo")
        self.assertFalse(Ticket.objects.exists())

    def test_edit_logs_each_changed_field_and_history_popup(self):
        t = self.new_ticket()
        r = self.client.post(reverse("ticket_detail", args=[t.number]), {
            "version": t.version, "status": "in_progress", "fault_type": "safety", "severity": "high",
            "fault_description": "Rung 4 cracked on left side", "work_done": "",
        })
        self.assertRedirects(r, reverse("ticket_detail", args=[t.number]))
        t.refresh_from_db()
        self.assertEqual(t.version, 2)
        changed = set(FieldChange.objects.filter(ticket=t, note="").values_list("field", flat=True))
        self.assertEqual(changed, {"status", "fault_description"})
        r = self.client.get(reverse("ticket_history", args=[t.number, "status"]))
        self.assertContains(r, "Open → In Progress")
        self.assertContains(r, "J. Smith")

    def test_concurrent_edit_is_refused(self):
        t = self.new_ticket()
        update_ticket(t, self.admin, {"work_done": "Replaced rung"}, expected_version=1)
        with self.assertRaises(ConflictError):
            update_ticket(t, self.user, {"work_done": "Something else"}, expected_version=1)
        r = self.client.post(reverse("ticket_detail", args=[t.number]), {
            "version": 1, "status": "open", "fault_type": "safety", "severity": "high",
            "fault_description": "Rung cracked", "work_done": "Mine",
        })
        self.assertContains(r, "Someone else saved this ticket")
        t.refresh_from_db()
        self.assertEqual(t.work_done, "Replaced rung")

    def test_resolve_and_reopen_need_permission(self):
        t = self.new_ticket()
        role = self.user.role
        role.permissions.remove(*role.permissions.filter(code__in=["resolve_ticket", "reopen_ticket"]))
        data = {"version": 1, "status": "resolved", "fault_type": "safety", "severity": "high", "fault_description": "Rung cracked", "work_done": ""}
        r = self.client.post(reverse("ticket_detail", args=[t.number]), data)
        self.assertEqual(r.status_code, 403)
        update_ticket(t, self.admin, {"status": "resolved"}, expected_version=1)
        data |= {"version": 2, "status": "open"}
        r = self.client.post(reverse("ticket_detail", args=[t.number]), data)
        self.assertEqual(r.status_code, 403)

    def test_remove_photo_hides_and_logs(self):
        t = create_ticket(self.item, self.user, {"fault_type": "cosmetic", "severity": "low"}, [jpeg()])
        photo = t.photos.get()
        r = self.client.post(reverse("photo_remove", args=[photo.pk]))
        self.assertEqual(r.status_code, 403)  # User role lacks remove_photo
        self.client.force_login(self.admin)
        self.client.post(reverse("photo_remove", args=[photo.pk]))
        photo.refresh_from_db()
        self.assertIsNotNone(photo.removed_at)
        self.assertTrue(FieldChange.objects.filter(ticket=t, field="photos", note="removed").exists())
        r = self.client.get(reverse("ticket_detail", args=[t.number]))
        self.assertNotContains(r, reverse("photo_thumb", args=[photo.pk]))

    def test_open_tickets_order(self):
        low = self.new_ticket(fault_type="cosmetic", severity="low")
        high = self.new_ticket(fault_type="functionality", severity="high")
        safety = self.new_ticket(fault_type="safety", severity="low")
        resolved = self.new_ticket()
        update_ticket(resolved, self.user, {"status": "resolved"}, expected_version=1)
        r = self.client.get(reverse("open_tickets"))
        codes = [t.code for t in r.context["page"]]
        self.assertEqual(codes, [safety.code, high.code, low.code])

    def test_login_required_everywhere(self):
        self.client.logout()
        t = self.new_ticket()
        for url in (reverse("home"), reverse("ticket_detail", args=[t.number]), reverse("item_list")):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302)
            self.assertIn(reverse("login"), r["Location"])


@override_settings(PHOTOS_DIR=Path(TMP_PHOTOS), SECURE_SSL_REDIRECT=False)
class ReportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("leon", password="x", role=Role.objects.get(name="Admin"))
        self.user = User.objects.create_user("jsmith", password="x", role=Role.objects.get(name="User"))
        ladder = ItemType.objects.create(name="Step ladder 3m")
        drill = ItemType.objects.create(name="Drill 18V")
        self.ladder_item = Item.objects.create(item_type=ladder, barcode="111", serial_number="LD-1")
        self.drill_item = Item.objects.create(item_type=drill, barcode="222", serial_number="DR-1")
        self.t1 = create_ticket(self.ladder_item, self.admin, {"fault_type": "safety", "severity": "high",
                                "fault_description": "Rung cracked – “bad”"}, [jpeg(), jpeg("b.jpg", (600, 900))])
        self.t2 = create_ticket(self.drill_item, self.admin, {"fault_type": "cosmetic", "severity": "low"})
        Ticket.objects.filter(pk=self.t2.pk).update(created_at="2025-06-01T10:00:00Z")
        self.client.force_login(self.admin)
        self.url = reverse("reports")

    def test_needs_export_permission(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_filters(self):
        r = self.client.get(self.url, {"action": "view", "severities": ["high"]})
        self.assertEqual(r.context["count"], 1)
        r = self.client.get(self.url, {"action": "view", "created_from": "2025-01-01", "created_to": "2025-12-31"})
        self.assertEqual([t.code for t in r.context["tickets"]], [self.t2.code])
        r = self.client.get(self.url, {"action": "view", "item_types": [self.ladder_item.item_type_id], "statuses": ["open"]})
        self.assertEqual(r.context["count"], 1)
        r = self.client.get(self.url, {"action": "view", "text": "rung"})
        self.assertEqual(r.context["count"], 1)
        r = self.client.get(self.url, {"action": "view"})
        self.assertEqual(r.context["count"], 2)

    def test_xlsx_with_photos(self):
        from openpyxl import load_workbook

        r = self.client.get(self.url, {"action": "xlsx", "include_photos": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        wb = load_workbook(BytesIO(r.content))
        ws = wb["Tickets"]
        self.assertEqual(ws.max_row, 3)
        self.assertEqual(ws["A2"].value, self.t2.code)  # oldest first
        self.assertEqual(len(ws._images), 2)

    def test_pdf_with_and_without_photos(self):
        plain = self.client.get(self.url, {"action": "pdf"})
        photos = self.client.get(self.url, {"action": "pdf", "include_photos": "on"})
        for r in (plain, photos):
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertGreater(len(photos.content), len(plain.content) + 5000)

    def test_empty_report(self):
        r = self.client.get(self.url, {"action": "pdf", "severities": ["medium"]})
        self.assertTrue(r.content.startswith(b"%PDF"))
        r = self.client.get(self.url, {"action": "xlsx", "severities": ["medium"]})
        self.assertEqual(r.status_code, 200)


class CopyDataScriptTests(TestCase):
    """deploy/windows/copy_data.py must copy everything and refuse to overwrite."""

    def test_copy_and_verify(self):
        import importlib.util
        import sqlite3

        spec = importlib.util.spec_from_file_location(
            "copy_data", Path(__file__).resolve().parent.parent / "deploy" / "windows" / "copy_data.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src", Path(tmp) / "dst"
            (src / "photos").mkdir(parents=True)
            con = sqlite3.connect(src / "db.sqlite3")
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE t (x)")
            con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(50)])
            con.commit()  # left open, so changes sit in the -wal file
            (src / "secret_key.txt").write_text("k")
            (src / "photos" / "a.jpg").write_bytes(b"x" * 1000)
            mod.main(src, dst)
            con.close()
            copy = sqlite3.connect(dst / "db.sqlite3")
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM t").fetchone()[0], 50)
            copy.close()
            self.assertEqual((dst / "photos" / "a.jpg").read_bytes(), b"x" * 1000)
            self.assertTrue((src / "db.sqlite3").exists())  # source untouched
            with self.assertRaises(SystemExit):
                mod.main(src, dst)
