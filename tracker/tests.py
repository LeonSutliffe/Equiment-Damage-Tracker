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
        self.assertContains(r, "Open → Repair in Progress")
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
        self.assertEqual(ws.max_row, 5)  # header, 2 tickets, blank row, total repair cost
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


@override_settings(SECURE_SSL_REDIRECT=False)
class CommentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("jsmith", password="x", display_name="J. Smith", role=Role.objects.get(name="User"))
        item = Item.objects.create(item_type=ItemType.objects.create(name="Ladder"), barcode="1", serial_number="S1")
        self.t = create_ticket(item, self.user, {"fault_type": "safety", "severity": "high"})
        self.client.force_login(self.user)

    def test_add_and_show_comment(self):
        url = reverse("comment_add", args=[self.t.number])
        r = self.client.post(url, {"text": "Ordered a new rung"})
        self.assertRedirects(r, reverse("ticket_detail", args=[self.t.number]) + "#comments", fetch_redirect_response=False)
        self.client.post(url, {"text": "   "})  # blank ignored
        self.assertEqual(self.t.comments.count(), 1)
        r = self.client.get(reverse("ticket_detail", args=[self.t.number]))
        self.assertContains(r, "Ordered a new rung")
        self.assertContains(r, "J. Smith")

    def test_comment_needs_edit_permission(self):
        role = self.user.role
        role.permissions.remove(*role.permissions.filter(code="edit_ticket"))
        r = self.client.post(reverse("comment_add", args=[self.t.number]), {"text": "x"})
        self.assertEqual(r.status_code, 403)

    def test_comments_in_reports(self):
        from openpyxl import load_workbook

        from .models import Comment

        Comment.objects.create(ticket=self.t, user=self.user, text="Waiting for parts")
        admin = User.objects.create_user("leon", password="x", role=Role.objects.get(name="Admin"))
        self.client.force_login(admin)
        r = self.client.get(reverse("reports"), {"action": "xlsx"})
        ws = load_workbook(BytesIO(r.content))["Tickets"]
        col = [c.value for c in ws[1]].index("Comments")
        self.assertIn("Waiting for parts", ws[2][col].value)
        r = self.client.get(reverse("reports"), {"action": "pdf"})
        self.assertTrue(r.content.startswith(b"%PDF"))


@override_settings(SECURE_SSL_REDIRECT=False)
class LabelTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user("leon", password="x", role=Role.objects.get(name="Admin"))
        item = Item.objects.create(item_type=ItemType.objects.create(name="Ladder"), barcode="501234567", serial_number="LD-1")
        for sev in ("low", "medium", "high"):
            create_ticket(item, admin, {"fault_type": "safety", "severity": sev})
        self.client.force_login(admin)

    def pages(self, content):
        return content.count(b"/Type /Page\n") or content.count(b"/Type /Page ") or content.count(b"/Type /Page>")

    def test_layout_geometry(self):
        from . import labels

        self.assertAlmostEqual(labels.LEFT, 4.75, places=2)
        self.assertAlmostEqual(labels.TOP, 10.7, places=2)
        x, y = labels.label_position(64)  # bottom-right label ends at the sheet's mirrored margins
        self.assertAlmostEqual(x + labels.LABEL_W, 210 - 4.75, places=2)
        self.assertAlmostEqual(y + labels.LABEL_H, 297 - 10.7, places=2)

    def test_labels_pdf(self):
        r = self.client.get(reverse("reports"), {"action": "labels"})
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("labels_", r["Content-Disposition"])
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_page_count(self):
        from .labels import build_labels_pdf

        tickets = list(Ticket.objects.select_related("item")) * 30  # 90 labels -> 2 sheets
        one = build_labels_pdf(tickets[:65])
        two = build_labels_pdf(tickets)
        filled = build_labels_pdf(tickets[:3], fill_templates=True, template_severity="high")
        offset = build_labels_pdf(tickets[:3], start_at=64)  # 64, 65, then next sheet
        import re

        from fpdf import FPDF  # noqa: F401

        count = lambda b: len(re.findall(rb"/Type /Page\b(?!s)", b))
        self.assertEqual((count(one), count(two), count(filled), count(offset)), (1, 2, 1, 2))


class HealthTests(TestCase):
    def test_health_ok_without_login(self):
        r = self.client.get("/health/", secure=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"ok")

    def test_health_reports_database_error(self):
        from unittest import mock

        with mock.patch("django.db.backends.utils.CursorWrapper.execute", side_effect=Exception("unable to open database file")):
            r = self.client.get("/health/")
        self.assertEqual(r.status_code, 503)
        self.assertIn(b"unable to open", r.content)


@override_settings(PHOTOS_DIR=Path(TMP_PHOTOS), SECURE_SSL_REDIRECT=False)
class NewFeatureTests(TestCase):
    def setUp(self):
        from accounts.models import AuditEvent

        self.AuditEvent = AuditEvent
        self.user = User.objects.create_user("jsmith", password="pw", role=Role.objects.get(name="User"))
        self.admin = User.objects.create_user("leon", password="pw", role=Role.objects.get(name="Admin"))
        ladder = ItemType.objects.create(name="Step ladder 3m")
        self.item = Item.objects.create(item_type=ladder, barcode="501", serial_number="LD-1")
        self.client.force_login(self.admin)

    def ticket(self, **kw):
        return create_ticket(self.item, self.admin, {"fault_type": "safety", "severity": "high"} | kw)

    # ---- duplicate warning
    def test_duplicate_warning_lists_open_tickets(self):
        r = self.client.get(reverse("ticket_create", args=[self.item.pk]))
        self.assertNotContains(r, "already has")
        t = self.ticket(fault_description="Rung cracked")
        resolved = self.ticket()
        update_ticket(resolved, self.admin, {"status": "resolved"}, expected_version=1)
        r = self.client.get(reverse("ticket_create", args=[self.item.pk]))
        self.assertContains(r, "already has 1 open ticket")
        self.assertContains(r, t.code)
        self.assertNotContains(r, resolved.code)

    # ---- repair costs
    def test_repair_cost_saved_logged_and_totalled(self):
        t = self.ticket(repair_cost="12.5")
        self.assertEqual(FieldChange.objects.get(ticket=t, field="repair_cost").new_value, "12.5")
        r = self.client.post(reverse("ticket_detail", args=[t.number]), {
            "version": 1, "status": "in_progress", "fault_type": "safety", "severity": "high",
            "repair_cost": "30.25"})
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db()
        self.assertEqual(str(t.repair_cost), "30.25")
        r = self.client.get(reverse("ticket_history", args=[t.number, "repair_cost"]))
        self.assertContains(r, "£30.25")
        self.ticket(repair_cost="10")
        r = self.client.get(reverse("reports"), {"action": "view"})
        self.assertEqual(str(r.context["total_cost"]), "40.25")
        self.assertContains(r, "£40.25")
        r = self.client.get(reverse("reports"), {"action": "xlsx"})
        from openpyxl import load_workbook

        ws = load_workbook(BytesIO(r.content))["Tickets"]
        col = [c.value for c in ws[1]].index("Repair cost") + 1
        self.assertTrue(str(ws.cell(row=5, column=col).value).startswith("=SUM("))
        self.assertEqual(self.client.get(reverse("reports"), {"action": "pdf"}).status_code, 200)

    def test_negative_cost_rejected(self):
        t = self.ticket()
        r = self.client.post(reverse("ticket_detail", args=[t.number]), {
            "version": 1, "status": "open", "fault_type": "safety", "severity": "high", "repair_cost": "-5"})
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertIsNone(t.repair_cost)

    # ---- write-off
    def test_write_off_and_reinstate(self):
        url = reverse("item_write_off", args=[self.item.pk])
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.post(url, {"reason": "Beyond repair"})
        self.assertRedirects(r, reverse("item_detail", args=[self.item.pk]))
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_written_off)
        self.assertEqual(self.item.written_off_by, self.admin)
        # No new tickets, hidden from the default item list, still findable.
        r = self.client.get(reverse("ticket_create", args=[self.item.pk]))
        self.assertRedirects(r, reverse("item_detail", args=[self.item.pk]))
        self.assertNotContains(self.client.get(reverse("item_list")), "LD-1")
        self.assertContains(self.client.get(reverse("item_list"), {"state": "written_off"}), "LD-1")
        self.assertRedirects(self.client.get(reverse("home"), {"q": "501"}), reverse("item_detail", args=[self.item.pk]))
        r = self.client.get(reverse("item_history", args=[self.item.pk, "write_off"]))
        self.assertContains(r, "Beyond repair")
        self.assertContains(self.client.get(reverse("item_history", args=[self.item.pk, "barcode"])), "Barcode history")
        self.client.post(reverse("item_reinstate", args=[self.item.pk]))
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_written_off)
        self.assertEqual(ItemChange.objects.filter(item=self.item, field="write_off").count(), 2)

    # ---- item history page
    def test_item_history_page(self):
        t = self.ticket(fault_description="Rung cracked", repair_cost="15")
        update_ticket(t, self.admin, {"status": "resolved", "work_done": "New rung"}, expected_version=1)
        self.client.post(reverse("comment_add", args=[t.number]), {"text": "Checked again"})
        self.ticket(fault_type="cosmetic")
        self.client.force_login(self.user)
        r = self.client.get(reverse("item_timeline", args=[self.item.pk]))
        self.assertEqual(r.status_code, 200)
        for text in ("Rung cracked", "Status changed from Open to Resolved", "Work Done: New rung", "Checked again",
                     "Safety × 1", "Cosmetic × 1", "£15.00", "Item added"):
            self.assertContains(r, text, msg_prefix=text)
        self.assertEqual(r.context["summary"]["tickets"], 2)
        self.assertEqual(r.context["summary"]["open"], 1)

    # ---- audit log
    def test_audit_log_records_logins_and_changes(self):
        self.client.logout()
        self.AuditEvent.objects.all().delete()
        self.client.post(reverse("login"), {"username": "jsmith", "password": "wrong"})
        self.client.post(reverse("login"), {"username": "jsmith", "password": "pw"})
        self.client.post(reverse("logout"))
        kinds = list(self.AuditEvent.objects.order_by("id").values_list("kind", flat=True))
        self.assertEqual(kinds, ["login_failed", "login", "logout"])
        self.client.force_login(self.admin)
        self.client.post(reverse("ticket_create", args=[self.item.pk]), {"fault_type": "safety", "severity": "high"})
        t = Ticket.objects.get()
        self.client.post(reverse("ticket_detail", args=[t.number]), {
            "version": 1, "status": "resolved", "fault_type": "safety", "severity": "high"})
        texts = list(self.AuditEvent.objects.filter(kind="ticket").values_list("text", flat=True))
        self.assertTrue(any("Opened T-00001" in x for x in texts))
        self.assertTrue(any("Status: Open → Resolved" in x for x in texts))
        r = self.client.get(reverse("audit_log"))
        self.assertContains(r, "Wrong password")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("audit_log")).status_code, 403)

    # ---- bulk actions
    def test_bulk_change_and_comment(self):
        a, b, c = self.ticket(), self.ticket(), self.ticket()
        url = reverse("bulk_tickets")
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url, {"tickets": [a.number], "status": "resolved"}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("open_tickets")), 'id="bulk-form"')
        r = self.client.post(url, {"tickets": [a.number, b.number], "status": "resolved", "comment": "Batch fixed",
                                   "next": reverse("open_tickets")})
        self.assertRedirects(r, reverse("open_tickets"))
        statuses = dict(Ticket.objects.values_list("number", "status"))
        self.assertEqual((statuses[a.number], statuses[b.number], statuses[c.number]), ("resolved", "resolved", "open"))
        self.assertEqual(FieldChange.objects.filter(field="status", new_value="resolved").count(), 2)
        self.assertEqual(a.comments.get().text, "Batch fixed")
        self.assertTrue(self.AuditEvent.objects.filter(kind="bulk", text__contains=a.code).exists())
        # Nothing chosen: refused with a message, nothing changes.
        r = self.client.post(url, {"tickets": [c.number]}, follow=True)
        self.assertContains(r, "Choose something to change")
        # An outside "next" address is ignored.
        r = self.client.post(url, {"tickets": [c.number], "severity": "low", "next": "https://evil.example/"})
        self.assertRedirects(r, reverse("open_tickets"))


TMP_DOCS = tempfile.mkdtemp()


@override_settings(PHOTOS_DIR=Path(TMP_PHOTOS), DOCUMENTS_DIR=Path(TMP_DOCS), SECURE_SSL_REDIRECT=False)
class DocumentAndRepairTimeTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_DOCS, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user("jsmith", password="pw", role=Role.objects.get(name="User"))
        self.admin = User.objects.create_user("leon", password="pw", role=Role.objects.get(name="Admin"))
        self.ladder = ItemType.objects.create(name="Step ladder 3m")
        self.item = Item.objects.create(item_type=self.ladder, barcode="501", serial_number="LD-1")
        self.other = Item.objects.create(item_type=self.ladder, barcode="502", serial_number="LD-2")
        self.client.force_login(self.admin)

    def pdf(self, name="Manual.pdf"):
        return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")

    def test_type_document_shows_on_every_item(self):
        r = self.client.post(reverse("document_add_item", args=[self.item.pk]),
                             {"file": self.pdf(), "title": "User manual", "attach_to": "type"})
        self.assertEqual(r.status_code, 302)
        from .models import Document

        doc = Document.objects.get()
        self.assertEqual(doc.item_type, self.ladder)
        self.assertIsNone(doc.item)
        self.assertTrue((Path(TMP_DOCS) / doc.file_name).is_file())
        self.assertContains(self.client.get(reverse("item_detail", args=[self.other.pk])), "User manual")
        # Any user with View can open it; PDFs open in the browser.
        self.client.force_login(self.user)
        r = self.client.get(reverse("document_open", args=[doc.pk]))
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("inline", r["Content-Disposition"])
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 test")
        # But can't add or remove without Manage documents.
        self.assertEqual(self.client.post(reverse("document_remove", args=[doc.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("document_add_type", args=[self.ladder.pk]),
                                          {"file": self.pdf()}).status_code, 403)

    def test_item_only_document_and_remove(self):
        self.client.post(reverse("document_add_item", args=[self.item.pk]),
                         {"file": self.pdf("cert.pdf"), "attach_to": "item"})
        from .models import Document

        doc = Document.objects.get()
        self.assertEqual((doc.item, doc.item_type, doc.title), (self.item, None, "cert"))
        self.assertNotContains(self.client.get(reverse("item_detail", args=[self.other.pk])), "<strong>cert</strong>")
        self.client.post(reverse("document_remove", args=[doc.pk]))
        doc.refresh_from_db()
        self.assertIsNotNone(doc.removed_at)
        self.assertTrue((Path(TMP_DOCS) / doc.file_name).is_file())  # file kept
        self.assertEqual(self.client.get(reverse("document_open", args=[doc.pk])).status_code, 404)
        from accounts.models import AuditEvent

        self.assertEqual(AuditEvent.objects.filter(kind="document").count(), 2)

    def test_item_type_page_upload_and_bad_files(self):
        r = self.client.post(reverse("document_add_type", args=[self.ladder.pk]),
                             {"file": SimpleUploadedFile("spec.docx", b"PK..."), "title": "Spec"})
        self.assertRedirects(r, reverse("item_type_edit", args=[self.ladder.pk]) + "#documents",
                             fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("item_type_edit", args=[self.ladder.pk])), "Spec")
        r = self.client.get(reverse("document_open", args=[1]))
        self.assertIn("attachment", r["Content-Disposition"])  # Word files download
        r = self.client.post(reverse("document_add_type", args=[self.ladder.pk]),
                             {"file": SimpleUploadedFile("run.exe", b"MZ")}, follow=True)
        self.assertContains(r, "can&#x27;t be added")
        from .models import Document

        self.assertEqual(Document.objects.count(), 1)

    def test_repair_time(self):
        t = create_ticket(self.item, self.admin, {"fault_type": "safety", "severity": "high", "repair_time": "1.5"})
        r = self.client.post(reverse("ticket_detail", args=[t.number]), {
            "version": 1, "status": "open", "fault_type": "safety", "severity": "high",
            "repair_time": "2.25", "repair_cost": "40"})
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db()
        self.assertEqual(str(t.repair_time), "2.25")
        r = self.client.get(reverse("ticket_history", args=[t.number, "repair_time"]))
        self.assertContains(r, "1.5 h")
        self.assertContains(r, "2.25 h")
        create_ticket(self.item, self.admin, {"fault_type": "cosmetic", "severity": "low", "repair_time": "0.75"})
        r = self.client.get(reverse("reports"), {"action": "view"})
        from decimal import Decimal

        self.assertEqual(r.context["total_hours"], Decimal("3"))
        r = self.client.get(reverse("item_timeline", args=[self.item.pk]))
        self.assertContains(r, "3 h")
        from openpyxl import load_workbook

        ws = load_workbook(BytesIO(self.client.get(reverse("reports"), {"action": "xlsx"}).content))["Tickets"]
        self.assertIn("Repair time (hours)", [c.value for c in ws[1]])
        self.assertEqual(self.client.get(reverse("reports"), {"action": "pdf"}).status_code, 200)


@override_settings(PHOTOS_DIR=Path(TMP_PHOTOS), SECURE_SSL_REDIRECT=False)
class PreviousJobTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("leon", password="pw", role=Role.objects.get(name="Admin"))
        self.item = Item.objects.create(item_type=ItemType.objects.create(name="Drill"), barcode="9001", serial_number="DR-9")
        self.client.force_login(self.admin)

    def test_previous_job_saved_logged_searched_and_reported(self):
        self.client.post(reverse("ticket_create", args=[self.item.pk]),
                         {"fault_type": "functionality", "severity": "medium", "previous_job": "Glastonbury 2026"})
        t = Ticket.objects.get()
        self.assertEqual(t.previous_job, "Glastonbury 2026")
        self.client.post(reverse("ticket_detail", args=[t.number]), {
            "version": 1, "status": "open", "fault_type": "functionality", "severity": "medium",
            "previous_job": "Reading Festival"})
        r = self.client.get(reverse("ticket_history", args=[t.number, "previous_job"]))
        self.assertContains(r, "Glastonbury 2026")
        self.assertContains(r, "Reading Festival")
        r = self.client.get(reverse("home"), {"q": "reading"})
        self.assertContains(r, t.code)
        r = self.client.get(reverse("reports"), {"action": "view", "text": "reading"})
        self.assertEqual(r.context["count"], 1)
        from openpyxl import load_workbook

        ws = load_workbook(BytesIO(self.client.get(reverse("reports"), {"action": "xlsx"}).content))["Tickets"]
        col = [c.value for c in ws[1]].index("Previous job")
        self.assertEqual(ws[2][col].value, "Reading Festival")
        self.assertContains(self.client.get(reverse("item_timeline", args=[self.item.pk])), "Reading Festival")


@override_settings(PHOTOS_DIR=Path(TMP_PHOTOS), SECURE_SSL_REDIRECT=False)
class ReportFieldChoiceTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user("leon", password="pw", role=Role.objects.get(name="Admin"))
        item = Item.objects.create(item_type=ItemType.objects.create(name="Drill"), barcode="9001", serial_number="DR-9")
        create_ticket(item, admin, {"fault_type": "safety", "severity": "high", "fault_description": "Chuck loose",
                                    "previous_job": "Secret job", "repair_cost": "12"})
        self.client.force_login(admin)

    def xlsx_headers(self, params):
        from openpyxl import load_workbook

        r = self.client.get(reverse("reports"), {"action": "xlsx"} | params)
        ws = load_workbook(BytesIO(r.content))["Tickets"]
        return [c.value for c in ws[1]], ws

    def test_only_chosen_fields_exported(self):
        headers, ws = self.xlsx_headers({"fields_set": "1", "fields": ["Severity", "Repair cost"]})
        self.assertEqual(headers, ["Ticket", "Severity", "Repair cost"])
        self.assertEqual(ws["C4"].value, "=SUM(C2:C2)")
        # Without a choice (e.g. an old link) everything is included.
        headers, _ = self.xlsx_headers({})
        self.assertIn("Previous job", headers)
        self.assertIn("Photos", headers)
        # PDF leaves unchosen fields out.
        r = self.client.get(reverse("reports"), {"action": "pdf", "fields_set": "1", "fields": ["Severity"]})
        self.assertEqual(r.status_code, 200)

    def test_none_chosen_is_refused(self):
        r = self.client.get(reverse("reports"), {"action": "xlsx", "fields_set": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Choose at least one field")

    def test_reports_page_has_chooser(self):
        r = self.client.get(reverse("reports"))
        self.assertContains(r, 'id="fields-dialog"')
        self.assertContains(r, 'value="Previous job"')


@override_settings(PHOTOS_DIR=Path(TMP_PHOTOS), SECURE_SSL_REDIRECT=False)
class ManufacturerTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("leon", password="pw", role=Role.objects.get(name="Admin"))
        self.client.force_login(self.admin)

    def test_manufacturer_and_model_name(self):
        r = self.client.post(reverse("item_type_create"), {"manufacturer": "Zarges", "name": "Step ladder 3m", "active": "on"})
        self.assertRedirects(r, reverse("item_type_list"))
        t = ItemType.objects.get()
        self.assertEqual(str(t), "Zarges Step ladder 3m")
        # Same model name from another manufacturer is fine; an exact repeat is not.
        self.client.post(reverse("item_type_create"), {"manufacturer": "Werner", "name": "Step ladder 3m", "active": "on"})
        r = self.client.post(reverse("item_type_create"), {"manufacturer": "zarges", "name": "step ladder 3M", "active": "on"})
        self.assertContains(r, "There is already an item type")
        self.assertEqual(ItemType.objects.count(), 2)
        self.assertContains(self.client.get(reverse("item_type_create")), "Model name")
        item = Item.objects.create(item_type=t, barcode="77", serial_number="Z-1")
        create_ticket(item, self.admin, {"fault_type": "safety", "severity": "high"})
        self.assertContains(self.client.get(reverse("item_detail", args=[item.pk])), "Zarges Step ladder 3m")
        r = self.client.get(reverse("home"), {"q": "zarg"})
        self.assertContains(r, "Z-1")
        from openpyxl import load_workbook

        ws = load_workbook(BytesIO(self.client.get(reverse("reports"), {"action": "xlsx"}).content))["Tickets"]
        headers = [c.value for c in ws[1]]
        self.assertEqual(ws[2][headers.index("Manufacturer")].value, "Zarges")
        self.assertEqual(ws[2][headers.index("Model name")].value, "Step ladder 3m")
        self.assertEqual(ws[2][headers.index("Item type")].value, "Zarges Step ladder 3m")


@override_settings(PHOTOS_DIR=Path(TMP_PHOTOS), SECURE_SSL_REDIRECT=False)
class CheckMeLabelTests(TestCase):
    def test_sheet_of_check_me_labels(self):
        admin = User.objects.create_user("leon", password="pw", role=Role.objects.get(name="Admin"))
        self.client.force_login(admin)
        r = self.client.get(reverse("reports"), {"action": "blank_labels", "template_colour": "checkme", "label_start": 1})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("write-in-labels", r["Content-Disposition"])
        from .labels import build_labels_pdf

        self.assertGreater(len(build_labels_pdf([], fill_templates=True, template_severity="checkme", start_at=60)), 1000)
