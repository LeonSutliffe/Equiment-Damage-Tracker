"""Ticket reports: filter tickets and export them as Excel or PDF, optionally with photos."""

import datetime as dt
from io import BytesIO

from django import forms
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import ItemType, Ticket, format_cost, format_hours

COLUMNS = ["Ticket", "Created", "Created by", "Status", "Fault Type", "Severity", "Item type", "Manufacturer", "Model name", "Barcode",
           "Serial number", "Previous job", "Fault Description", "Work Done", "Repair cost", "Repair time (hours)",
           "Comments", "Last updated"]
# Everything except the ticket number (always included) can be left out of exports.
CHOOSABLE = COLUMNS[1:] + ["Photo count"]


class ReportForm(forms.Form):
    created_from = forms.DateField(required=False, label="Created from", widget=forms.DateInput(attrs={"type": "date"}))
    created_to = forms.DateField(required=False, label="Created to", widget=forms.DateInput(attrs={"type": "date"}))
    item_types = forms.ModelMultipleChoiceField(
        queryset=ItemType.objects.all(), required=False, label="Item type", widget=forms.CheckboxSelectMultiple
    )
    statuses = forms.MultipleChoiceField(
        choices=Ticket.Status.choices, required=False, label="Status", widget=forms.CheckboxSelectMultiple
    )
    fault_types = forms.MultipleChoiceField(
        choices=Ticket.FaultType.choices, required=False, label="Fault Type", widget=forms.CheckboxSelectMultiple
    )
    severities = forms.MultipleChoiceField(
        choices=Ticket.Severity.choices, required=False, label="Severity", widget=forms.CheckboxSelectMultiple
    )
    text = forms.CharField(
        required=False, label="Contains text",
        help_text="Searches fault description, work done, previous job, barcode and serial number.",
    )
    include_photos = forms.BooleanField(required=False, label="Include photos")
    fields = forms.MultipleChoiceField(
        choices=[(c, c) for c in CHOOSABLE], required=False, initial=CHOOSABLE, label="Fields to include",
        widget=forms.CheckboxSelectMultiple,
    )
    fields_set = forms.CharField(required=False, widget=forms.HiddenInput, initial="1")

    # Sticker sheet options (65 per A4 sheet).
    label_start = forms.IntegerField(
        required=False, min_value=1, max_value=65, initial=1, label="Start at label",
        help_text="1 = top left. Use a later number to finish a part-used sheet.",
    )
    fill_templates = forms.BooleanField(
        required=False, label="Fill the rest of the last sheet with write-in labels"
    )
    template_colour = forms.ChoiceField(
        required=False, label="Write-in label colour",
        choices=[("none", "Grey")] + [(v, l) for v, l in Ticket.Severity.choices] + [("resolved", "Green (resolved)"),
                                                                                   ("checkme", "CHECK ME (pink)")],
    )
    label_outlines = forms.BooleanField(required=False, label="Draw label outlines (for a test print on plain paper)")

    def clean(self):
        data = super().clean()
        if data.get("created_from") and data.get("created_to") and data["created_from"] > data["created_to"]:
            raise forms.ValidationError("The 'from' date is after the 'to' date.")
        if data.get("fields_set") and not data.get("fields"):
            raise forms.ValidationError("Choose at least one field to include (Choose fields…).")
        return data


def selected_columns(data):
    """The chosen fields, in screen order; all of them if the choice wasn't sent (e.g. an old link)."""
    chosen = data.get("fields") if data.get("fields_set") else None
    if not chosen:
        return list(CHOOSABLE)
    return [c for c in CHOOSABLE if c in chosen]


def _day_start(day):
    return timezone.make_aware(dt.datetime.combine(day, dt.time.min))


def filter_tickets(data):
    tickets = Ticket.objects.select_related("item__item_type", "created_by").order_by("created_at", "number")
    if data.get("created_from"):
        tickets = tickets.filter(created_at__gte=_day_start(data["created_from"]))
    if data.get("created_to"):
        tickets = tickets.filter(created_at__lt=_day_start(data["created_to"] + dt.timedelta(days=1)))
    if data.get("item_types"):
        tickets = tickets.filter(item__item_type__in=data["item_types"])
    if data.get("statuses"):
        tickets = tickets.filter(status__in=data["statuses"])
    if data.get("fault_types"):
        tickets = tickets.filter(fault_type__in=data["fault_types"])
    if data.get("severities"):
        tickets = tickets.filter(severity__in=data["severities"])
    if data.get("text"):
        t = data["text"].strip()
        tickets = tickets.filter(
            Q(fault_description__icontains=t) | Q(work_done__icontains=t) | Q(previous_job__icontains=t)
            | Q(item__barcode__icontains=t) | Q(item__serial_number__icontains=t)
        )
    return tickets


def describe_filters(data):
    """Human-readable list of (label, value) for the report header."""
    out = []
    if data.get("created_from") or data.get("created_to"):
        a = data["created_from"].strftime("%d %b %Y") if data.get("created_from") else "the start"
        b = data["created_to"].strftime("%d %b %Y") if data.get("created_to") else "today"
        out.append(("Created", f"{a} to {b}"))
    if data.get("item_types"):
        out.append(("Item type", ", ".join(str(t) for t in data["item_types"])))
    for key, label, enum in (("statuses", "Status", Ticket.Status), ("fault_types", "Fault Type", Ticket.FaultType),
                             ("severities", "Severity", Ticket.Severity)):
        if data.get(key):
            out.append((label, ", ".join(enum(v).label for v in data[key])))
    if data.get("text"):
        out.append(("Contains text", data["text"]))
    return out or [("Filters", "All tickets")]


def _local(value):
    return timezone.localtime(value).strftime("%d %b %Y %H:%M") if value else ""


def _photos(ticket):
    return [p for p in ticket.photos.all() if p.removed_at is None]


def ticket_row(t):
    return {
        "Ticket": t.code,
        "Created": _local(t.created_at),
        "Created by": t.created_by.label if t.created_by else "",
        "Status": t.get_status_display(),
        "Fault Type": t.get_fault_type_display(),
        "Severity": t.get_severity_display(),
        "Item type": str(t.item.item_type),
        "Manufacturer": t.item.item_type.manufacturer,
        "Model name": t.item.item_type.name,
        "Barcode": t.item.barcode,
        "Serial number": t.item.serial_number,
        "Previous job": t.previous_job,
        "Fault Description": t.fault_description,
        "Work Done": t.work_done,
        "Repair cost": t.repair_cost if t.repair_cost is not None else "",
        "Repair time (hours)": t.repair_time if t.repair_time is not None else "",
        "Comments": "\n".join(
            f"{_local(c.created_at)} {c.user.label if c.user else '(deleted user)'}: {c.text}" for c in t.comments.all()
        ),
        "Last updated": _local(t.updated_at),
    }


# ------------------------------------------------------------------ Excel


def build_xlsx(tickets, data):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    include_photos = data.get("include_photos")
    wb = Workbook()
    ws = wb.active
    ws.title = "Tickets"
    tickets = list(tickets.prefetch_related("photos", "comments__user"))

    chosen = selected_columns(data)
    headers = ["Ticket"] + [c for c in COLUMNS[1:] if c in chosen] + (["Photos"] if "Photo count" in chosen else [])
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="14213D")
        cell.alignment = Alignment(vertical="center")
    widths = {"Ticket": 10, "Created": 17, "Created by": 14, "Status": 12, "Fault Type": 13, "Severity": 9,
              "Item type": 28, "Manufacturer": 16, "Model name": 20, "Barcode": 15, "Serial number": 15, "Previous job": 22, "Fault Description": 45, "Work Done": 45,
              "Repair cost": 11, "Repair time (hours)": 11, "Comments": 45, "Last updated": 17, "Photos": 8}
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(h, 14)

    photo_col = len(headers) + 1  # thumbnails go to the right of the table
    thumb_px, gap_px = 110, 4
    for r, t in enumerate(tickets, start=2):
        row = ticket_row(t)
        photos = _photos(t)
        row["Photos"] = len(photos)
        ws.append([row[h] for h in headers])
        for cell in ws[r]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        if include_photos and photos:
            ws.row_dimensions[r].height = thumb_px * 0.75 + 6  # points
            for i, p in enumerate(photos):
                path = settings.PHOTOS_DIR / p.thumbnail_file_name
                if not path.is_file():
                    continue
                img = XLImage(str(path))
                scale = thumb_px / max(img.width, img.height)
                img.width, img.height = int(img.width * scale), int(img.height * scale)
                col = photo_col + i
                ws.column_dimensions[get_column_letter(col)].width = (thumb_px + gap_px) / 7
                ws.add_image(img, f"{get_column_letter(col)}{r}")
    if include_photos:
        ws.cell(row=1, column=photo_col, value="Photo thumbnails").font = Font(bold=True)
    total_row = len(tickets) + 3  # one blank row, so sorting and filtering leave the totals alone
    for name, fmt in (("Repair cost", "£#,##0.00"), ("Repair time (hours)", "0.00")):
        if name not in headers:
            continue
        col = get_column_letter(headers.index(name) + 1)
        for r in range(2, len(tickets) + 2):
            ws[f"{col}{r}"].number_format = fmt
        if tickets:
            ws.cell(row=total_row, column=1, value="Totals").font = Font(bold=True)
            total = ws[f"{col}{total_row}"]
            total.value = f"=SUM({col}2:{col}{len(tickets) + 1})"
            total.number_format = fmt
            total.font = Font(bold=True)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(len(tickets) + 1, 1)}"

    info = wb.create_sheet("Report")
    info.append(["Equipment Damage Tracker report"])
    info["A1"].font = Font(bold=True, size=14)
    info.append(["Generated", timezone.localtime().strftime("%d %b %Y %H:%M")])
    info.append(["Tickets", len(tickets)])
    info.append(["Total repair cost", format_cost(sum((t.repair_cost or 0) for t in tickets))])
    info.append(["Total repair time", format_hours(sum((t.repair_time or 0) for t in tickets))])
    for label, value in describe_filters(data):
        info.append([label, value])
    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 60

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ PDF

_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]
_REPLACE = {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "...", "•": "-", "→": "->"}


def _setup_font(pdf):
    """Use a Unicode TrueType font if one is installed, else Helvetica (Latin-1 only)."""
    import os

    for regular, bold in _FONT_CANDIDATES:
        if os.path.isfile(regular) and os.path.isfile(bold):
            pdf.add_font("Body", "", regular)
            pdf.add_font("Body", "B", bold)
            return "Body", False
    return "Helvetica", True


def _pdf_image(path, edge=900):
    """A smaller JPEG copy of a photo, so PDFs with many photos stay a sensible size."""
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((edge, edge))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=80)
        buf.seek(0)
        return buf, im.width, im.height


def build_pdf(tickets, data):
    from fpdf import FPDF

    include_photos = data.get("include_photos")
    tickets = list(tickets.prefetch_related("photos", "comments__user"))
    generated = timezone.localtime().strftime("%d %b %Y %H:%M")

    class PDF(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font(font, "", 8)
            self.set_text_color(110)
            self.cell(0, 6, clean(f"Equipment Damage Tracker report - generated {generated} - page {self.page_no()}/{{nb}}"),
                      align="C")

    pdf = PDF(format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(14, 14, 14)
    font, latin1_only = _setup_font(pdf)

    def clean(text):
        text = str(text or "")
        if latin1_only:
            for a, b in _REPLACE.items():
                text = text.replace(a, b)
            text = text.encode("latin-1", "replace").decode("latin-1")
        return text

    pdf.add_page()
    width = pdf.epw
    pdf.set_font(font, "B", 16)
    pdf.cell(0, 9, clean("Ticket report"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font, "", 9)
    pdf.set_text_color(90)
    for label, value in describe_filters(data):
        pdf.multi_cell(0, 5, clean(f"{label}: {value}"), new_x="LMARGIN", new_y="NEXT")
    chosen_cols = set(selected_columns(data))
    summary = [f"{len(tickets)} ticket{'s' if len(tickets) != 1 else ''}"]
    if "Repair cost" in chosen_cols:
        summary.append(f"total repair cost {format_cost(sum((t.repair_cost or 0) for t in tickets))}")
    if "Repair time (hours)" in chosen_cols:
        summary.append(f"total repair time {format_hours(sum((t.repair_time or 0) for t in tickets))}")
    pdf.multi_cell(0, 5, clean(", ".join(summary)), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(3)

    if not tickets:
        pdf.set_font(font, "", 11)
        pdf.cell(0, 8, clean("No tickets match these filters."))

    thumb_w, gap = 42, 3
    chosen = set(selected_columns(data))

    def pick(*pairs):
        return [text for name, text in pairs if name in chosen]

    for t in tickets:
        row = ticket_row(t)
        photos = _photos(t) if include_photos else []
        # Start a new page rather than splitting a short ticket header from its body.
        if pdf.will_page_break(30):
            pdf.add_page()
        pdf.set_draw_color(200)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
        pdf.ln(2)
        pdf.set_font(font, "B", 12)
        pdf.cell(0, 7, clean("  -  ".join([t.code] + pick(("Item type", row["Item type"])))),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font, "", 9)
        ids = "   ".join(pick(("Barcode", f"Barcode {row['Barcode']}"), ("Serial number", f"Serial {row['Serial number']}")))
        facts = pick(
            ("Status", row["Status"]), ("Fault Type", row["Fault Type"]), ("Severity", f"Severity {row['Severity']}"),
            ("Repair cost", f"Repair cost {format_cost(t.repair_cost)}" if t.repair_cost is not None else ""),
            ("Repair time (hours)", f"Repair time {format_hours(t.repair_time)}" if t.repair_time is not None else ""),
        )
        line = "   |   ".join(x for x in [ids] + facts if x)
        if line:
            pdf.multi_cell(0, 5, clean(line), new_x="LMARGIN", new_y="NEXT")
        dates = "   ".join(pick(
            ("Created", f"Created {row['Created']}"), ("Created by", f"by {row['Created by'] or '-'}"),
            ("Last updated", f"Last updated {row['Last updated']}"),
        ))
        if dates:
            pdf.set_text_color(90)
            pdf.multi_cell(0, 5, clean(dates), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0)
        for label in ("Previous job", "Fault Description", "Work Done", "Comments"):
            if label in chosen and row[label]:
                pdf.set_font(font, "B", 9)
                pdf.cell(0, 5, clean(label), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font(font, "", 10)
                pdf.multi_cell(0, 5, clean(row[label]), new_x="LMARGIN", new_y="NEXT")
        if photos:
            pdf.ln(1)
            per_row = max(1, int((width + gap) // (thumb_w + gap)))
            paths = [settings.PHOTOS_DIR / p.file_name for p in photos]
            paths = [p for p in paths if p.is_file()]
            for start in range(0, len(paths), per_row):
                if pdf.will_page_break(thumb_w):
                    pdf.add_page()
                row_top, row_h = pdf.get_y(), 0
                for col, path in enumerate(paths[start:start + per_row]):
                    jpeg, w, h = _pdf_image(path)
                    img_w, img_h = (thumb_w, thumb_w * h / w) if w >= h else (thumb_w * w / h, thumb_w)
                    pdf.image(jpeg, x=pdf.l_margin + col * (thumb_w + gap), y=row_top, w=img_w, h=img_h)
                    row_h = max(row_h, img_h)
                pdf.set_y(row_top + row_h + gap)
        pdf.ln(3)

    return bytes(pdf.output())
