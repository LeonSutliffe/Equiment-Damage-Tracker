"""Printable sticker sheets: 65 labels per A4 sheet, 38.1 x 21.2 mm (5 across, 13 down).

Matches the common 65-up layout (e.g. Avery L7651 and compatibles). Print at 100% /
"Actual size" so the labels line up.
"""


from .models import Ticket

# Sheet geometry in millimetres.
PAGE_W, PAGE_H = 210.0, 297.0
COLS, ROWS = 5, 13
PER_SHEET = COLS * ROWS
LABEL_W, LABEL_H = 38.1, 21.2
H_PITCH, V_PITCH = 40.6, 21.2  # 2.5 mm gap between columns, none between rows
LEFT = (PAGE_W - (COLS - 1) * H_PITCH - LABEL_W) / 2  # 4.75 mm
TOP = (PAGE_H - (ROWS - 1) * V_PITCH - LABEL_H) / 2  # 10.7 mm

# Severity colours: strong band colour and pale fill.
COLOURS = {
    Ticket.Severity.HIGH: ((196, 32, 33), (253, 228, 226)),
    Ticket.Severity.MEDIUM: ((224, 140, 0), (255, 240, 205)),
    Ticket.Severity.LOW: ((22, 130, 72), (220, 245, 228)),
    "none": ((90, 98, 112), (238, 240, 243)),
}

PAD = 1.6  # inner margin so text stays clear of the cut edge


def label_position(index):
    """Top-left corner (x, y) in mm of label number `index` (0-based) on its sheet."""
    i = index % PER_SHEET
    return LEFT + (i % COLS) * H_PITCH, TOP + (i // COLS) * V_PITCH


def build_labels_pdf(tickets, fill_templates=False, template_severity="none", start_at=1, outlines=False):
    from fpdf import FPDF

    from .reports import _setup_font

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(0, 0, 0)
    font, latin1_only = _setup_font(pdf)

    def clean(text):
        text = str(text or "")
        return text.encode("latin-1", "replace").decode("latin-1") if latin1_only else text

    def fit(text, size, width, style=""):
        """Largest font size up to `size` at which `text` fits in `width` mm."""
        while size > 4:
            pdf.set_font(font, style, size)
            if pdf.get_string_width(text) <= width:
                break
            size -= 0.25
        return size

    def band(x, y, severity, title):
        strong, pale = COLOURS.get(severity, COLOURS["none"])
        pdf.set_fill_color(*pale)
        pdf.rect(x, y, LABEL_W, LABEL_H, style="F")
        pdf.set_fill_color(*strong)
        pdf.rect(x, y, LABEL_W, 6.0, style="F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(font, "B", 9)
        pdf.set_xy(x + PAD, y + 0.4)
        pdf.cell(LABEL_W - 2 * PAD, 5.2, clean(title), align="L")
        if severity in COLOURS and severity != "none":
            pdf.set_font(font, "B", 6.5)
            pdf.set_xy(x + PAD, y + 0.4)
            pdf.cell(LABEL_W - 2 * PAD, 5.2, clean(Ticket.Severity(severity).label.upper()), align="R")
        pdf.set_text_color(20, 20, 20)

    def ticket_label(x, y, t):
        band(x, y, t.severity, t.code)
        inner = LABEL_W - 2 * PAD
        for i, (tag, value) in enumerate((("BC", t.item.barcode), ("SN", t.item.serial_number))):
            line_y = y + 7.3 + i * 6.4
            pdf.set_font(font, "B", 6)
            pdf.set_text_color(90, 90, 90)
            pdf.set_xy(x + PAD, line_y)
            pdf.cell(5, 5.4, tag)
            text = clean(value)
            fit(text, 10, inner - 5, "B")
            pdf.set_text_color(20, 20, 20)
            pdf.set_xy(x + PAD + 5, line_y)
            pdf.cell(inner - 5, 5.4, text)

    def template_label(x, y, severity):
        band(x, y, severity, "")
        strong, _ = COLOURS.get(severity, COLOURS["none"])
        pdf.set_draw_color(*strong)
        pdf.set_line_width(0.3)
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(x + PAD, y + 7.2, LABEL_W - 2 * PAD, LABEL_H - 7.2 - PAD, style="DF")
        # Faint guide line splitting the box into two writing lines.
        pdf.set_draw_color(205, 205, 205)
        pdf.set_line_width(0.15)
        mid = y + 7.2 + (LABEL_H - 7.2 - PAD) / 2
        pdf.line(x + PAD + 1, mid, x + LABEL_W - PAD - 1, mid)
        pdf.set_font(font, "", 6)
        pdf.set_text_color(150, 150, 150)
        pdf.set_xy(x + PAD + 0.6, y + 7.4)
        pdf.cell(6, 3, "T-")
        pdf.set_text_color(20, 20, 20)

    tickets = list(tickets)
    slot = max(1, min(int(start_at or 1), PER_SHEET)) - 1  # skip labels already used on the first sheet
    pdf.add_page()

    def next_slot():
        nonlocal slot
        if slot and slot % PER_SHEET == 0:
            pdf.add_page()
        x, y = label_position(slot)
        slot += 1
        return x, y

    for t in tickets:
        x, y = next_slot()
        ticket_label(x, y, t)
    if fill_templates and slot % PER_SHEET:
        while slot % PER_SHEET:
            x, y = next_slot()
            template_label(x, y, template_severity)
    elif not tickets and fill_templates:  # only templates wanted: one full sheet
        while slot < PER_SHEET:
            x, y = next_slot()
            template_label(x, y, template_severity)

    if outlines:  # thin grey outlines, for test prints on plain paper
        pdf.set_draw_color(180, 180, 180)
        pdf.set_line_width(0.1)
        for page in range(1, pdf.pages_count + 1):
            pdf.page = page
            for i in range(PER_SHEET):
                x, y = label_position(i)
                pdf.rect(x, y, LABEL_W, LABEL_H)

    return bytes(pdf.output())
