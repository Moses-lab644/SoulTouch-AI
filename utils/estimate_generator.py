"""
estimate_generator.py
Generates the painting cost estimate PDF in two flavours:
  1. Customer version  – Soul-Touch / Godtech AI branded
  2. Painter version   – Painter's own business name + placeholder logo area

Uses the same DejaVuSans font stack and colour palette as po_generator.py
so all bot-generated documents look like they come from the same design system.
"""

import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io

# ─── Font registration ───────────────────────────────────────────────────────

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:
    FONT_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "fonts"
    )

    pdfmetrics.registerFont(
        TTFont(
            "DejaVuSans",
            os.path.join(FONT_DIR, "DejaVuSans.ttf")
        )
    )

    pdfmetrics.registerFont(
        TTFont(
            "DejaVuSans-Bold",
            os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
        )
    )

    pdfmetrics.registerFontFamily(
        "DejaVuSans",
        normal="DejaVuSans",
        bold="DejaVuSans-Bold",
        italic="DejaVuSans",
        boldItalic="DejaVuSans-Bold",
    )

    FONT_NORMAL = "DejaVuSans"
    FONT_BOLD = "DejaVuSans-Bold"

except Exception as e:
    print(f"Font registration failed: {e}")

    FONT_NORMAL = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"


# ─── Colours ─────────────────────────────────────────────────────────────────
NAVY      = colors.HexColor("#1B3A6B")
RED       = colors.HexColor("#C0392B")
GOLD      = colors.HexColor("#B8860B")
WHITE     = colors.white
LIGHT     = colors.HexColor("#EEF3FB")
MIDBLUE   = colors.HexColor("#D6E4F7")
GREY      = colors.HexColor("#666666")
GREEN     = colors.HexColor("#1E7B45")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")


def naira(amount):
    if amount is None or amount == "":
        return ""
    return f"\u20a6{float(amount):,.2f}"

def _styles():
    base = getSampleStyleSheet()
    return {
        "h1":     ParagraphStyle("h1",   fontName=FONT_BOLD,   fontSize=20, textColor=NAVY,  spaceAfter=4),
        "h2":     ParagraphStyle("h2",   fontName=FONT_BOLD,   fontSize=13, textColor=NAVY,  spaceBefore=10, spaceAfter=6),
        "normal": ParagraphStyle("norm", fontName=FONT_NORMAL, fontSize=9,  leading=13),
        "small":  ParagraphStyle("sm",   fontName=FONT_NORMAL, fontSize=8,  textColor=GREY,  leading=11),
        "right":  ParagraphStyle("rt",   fontName=FONT_NORMAL, fontSize=9,  alignment=TA_RIGHT),
        "center": ParagraphStyle("ct",   fontName=FONT_NORMAL, fontSize=9,  alignment=TA_CENTER),
        "red":    ParagraphStyle("red",  fontName=FONT_BOLD,   fontSize=16, textColor=RED,   alignment=TA_CENTER),
        "gold":   ParagraphStyle("gld",  fontName=FONT_BOLD,   fontSize=16, textColor=GOLD,  alignment=TA_CENTER),
        "footer": ParagraphStyle("ft",   fontName=FONT_NORMAL, fontSize=7.5, textColor=GREY, alignment=TA_CENTER),
        "note":   ParagraphStyle("nt",   fontName=FONT_NORMAL, fontSize=8.5, textColor=colors.HexColor("#555555"), leading=12),
    }
def _divider(color=None):
    return HRFlowable(width="100%", thickness=1, color=color or NAVY, spaceAfter=8, spaceBefore=6)


def _hdr_cell(text, w, align=TA_CENTER):
    s = ParagraphStyle("hc", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=WHITE, alignment=align)
    return Table([[Paragraph(text, s)]], colWidths=[w],
                 style=[("BACKGROUND", (0,0), (-1,-1), NAVY),
                        ("TOPPADDING", (0,0), (-1,-1), 5),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                        ("LEFTPADDING", (0,0), (-1,-1), 6),
                        ("RIGHTPADDING", (0,0), (-1,-1), 6)])


def _build_estimate_table(estimate_dict, brand_display_name):
    """
    Builds the main estimate table from a build_full_estimate() result dict.
    Returns a reportlab Table flowable.
    """
    s = _styles()
    norm = ParagraphStyle("tn", fontName="DejaVuSans", fontSize=8.5, leading=12)
    bold = ParagraphStyle("tb", fontName="DejaVuSans-Bold", fontSize=8.5, leading=12)
    navy_bold = ParagraphStyle("nb", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=NAVY, leading=12)

    COL = [28, 240, 72, 90, 90]   # S/N | Description | Qty | Unit Price | Amount
    TW  = sum(COL)

    def hrow(letter, title):
        return [Paragraph(letter, navy_bold),
                Paragraph(title, navy_bold), "", "", ""]

    def lrow(sn, desc, qty, unit, amount):
        return [Paragraph(str(sn), norm),
                Paragraph(str(desc), norm),
                Paragraph(str(qty), ParagraphStyle("tc", fontName="DejaVuSans", fontSize=8.5, alignment=TA_CENTER)),
                Paragraph(naira(unit) if unit else "", ParagraphStyle("tr", fontName="DejaVuSans", fontSize=8.5, alignment=TA_RIGHT)),
                Paragraph(naira(amount) if amount else "", ParagraphStyle("trb", fontName="DejaVuSans-Bold", fontSize=8.5, alignment=TA_RIGHT))]

    def srow(label, amount):
        return ["", Paragraph(label, ParagraphStyle("sl", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=NAVY, alignment=TA_RIGHT)),
                "", "", Paragraph(naira(amount), ParagraphStyle("sr", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=NAVY, alignment=TA_RIGHT))]

    rows = []

    # ── header
    rows.append([
        Paragraph("S/N",  ParagraphStyle("hh", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=WHITE, alignment=TA_CENTER)),
        Paragraph("Description", ParagraphStyle("hh2", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=WHITE)),
        Paragraph("Qty",  ParagraphStyle("hh3", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=WHITE, alignment=TA_CENTER)),
        Paragraph("Unit Price (\u20a6)", ParagraphStyle("hh4", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=WHITE, alignment=TA_RIGHT)),
        Paragraph("Amount (\u20a6)",     ParagraphStyle("hh5", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=WHITE, alignment=TA_RIGHT)),
    ])

    # ── 1. Surface Area
    rows.append(hrow("1", "MEASURED SURFACE AREA"))
    rows.append(lrow("", "Interior Wall Area",   f"{estimate_dict['interior_area_m2']:.4f} m\u00b2", None, None))
    rows.append(lrow("", "Exterior Wall Area",   f"{estimate_dict['exterior_area_m2']:.4f} m\u00b2", None, None))
    rows.append(lrow("", "Total Surface Area",   f"{estimate_dict['total_area_m2']:.4f} m\u00b2",    None, None))

    # ── 2. Screeding
    sc = estimate_dict["sections"].get("screeding")
    if sc:
        rows.append(hrow("2", "SCREEDING & SURFACE PREPARATION"))
        rows.append(lrow("1", "Stabilizing Solution (Interior & Exterior)",
                         f"{sc['stabilizing_solution']['drums_needed']} drums",
                         sc['stabilizing_solution']['unit_price'],
                         sc['stabilizing_solution']['total_cost']))
        rows.append(lrow("2", f"Putty \u2013 {sc['putty']['product_name']} (Total Area \u00f7 14 = {sc['putty']['drums_needed']} drums)",
                         f"{sc['putty']['drums_needed']} drums",
                         sc['putty']['unit_price'],
                         sc['putty']['total_cost']))
        rows.append(srow("Subtotal \u2013 Screeding", sc["subtotal"]))

    # ── 3. Painting
    pt = estimate_dict["sections"].get("painting")
    if pt:
        rows.append(hrow("3", f"PAINTING ({brand_display_name})"))
        sn = 3
        if pt.get("interior") and pt["interior"]:
            ip = pt["interior"]
            rows.append(lrow(sn, f"Interior Paint \u2013 {ip['product_name']} \u2013 {ip['description']}",
                             f"{ip['units_needed']} drums", ip["unit_price"], ip["total_cost"]))
            sn += 1
        if pt.get("exterior") and pt["exterior"]:
            ep = pt["exterior"]
            rows.append(lrow(sn, f"Exterior Paint \u2013 {ep['product_name']} \u2013 {ep['description']}",
                             f"{ep['units_needed']} drums", ep["unit_price"], ep["total_cost"]))
            sn += 1
        if pt.get("deep_colour_charge", 0) > 0:
            rows.append(lrow(sn, "10% Deep Colour Mixing Surcharge", "", "", pt["deep_colour_charge"]))
            sn += 1
        rows.append(srow("Subtotal \u2013 Painting Materials", pt["subtotal"]))

    # ── 4. Labour
    lb = estimate_dict["sections"].get("labour")
    if lb:
        rows.append(hrow("4", "LABOUR"))
        rows.append(lrow("", "Painting, Screeding & Surface Preparation Labour",
                         f"{estimate_dict['total_area_m2']:.4f} m\u00b2",
                         1500.00, lb["total_cost"]))

    # ── 5. Equipment & Sundries
    eq = estimate_dict["sections"].get("equipment", {})
    su = estimate_dict["sections"].get("sundries", {})
    rows.append(hrow("5", "EQUIPMENT & SUNDRIES"))
    line_sn = 5
    sc_cost = eq.get("scaffold_cost", 0) if isinstance(eq, dict) else 0
    ld_cost = eq.get("ladder_cost", 0) if isinstance(eq, dict) else 0
    if sc_cost > 0:
        days = round(sc_cost / 12000)
        rows.append(lrow(line_sn, "Scaffold Rental", f"{days} day{'s' if days != 1 else ''}", 12000, sc_cost))
        line_sn += 1
    if ld_cost > 0:
        days = round(ld_cost / 5000)
        rows.append(lrow(line_sn, "Ladder Rental", f"{days} day{'s' if days != 1 else ''}", 5000, ld_cost))
        line_sn += 1
    su_cost = su.get("total_cost", 50000)
    rows.append(lrow(line_sn, "Sundry (Transport, Covering Sheet, Masking Tape, Abrasive Paper)", "", "", su_cost))
    equip_sundry_total = eq.get("total_cost", 0) + su_cost
    rows.append(srow("Subtotal \u2013 Equipment & Sundries", equip_sundry_total))

    # ── Grand Total
    rows.append([
        "",
        Paragraph("GRAND TOTAL", ParagraphStyle("gt", fontName="DejaVuSans-Bold", fontSize=9.5, textColor=WHITE, alignment=TA_RIGHT)),
        "", "",
        Paragraph(naira(estimate_dict["grand_total"]), ParagraphStyle("gta", fontName="DejaVuSans-Bold", fontSize=9.5, textColor=WHITE, alignment=TA_RIGHT)),
    ])

    # ── determine which rows are which type for styling
    header_rows   = [0]
    section_rows  = []
    subtotal_rows = []
    grand_row     = len(rows) - 1
    data_rows     = []

    i = 1
    while i < len(rows) - 1:
        cell1_text = rows[i][1].text if hasattr(rows[i][1], 'text') else ""
        cell0_text = rows[i][0].text if hasattr(rows[i][0], 'text') else ""
        # Section header: col 0 is a single capital letter
        if isinstance(rows[i][0], Paragraph) and hasattr(rows[i][0], '_cellvalues'):
            pass
        # Use the paragraph text to classify
        para1 = rows[i][1]
        para0 = rows[i][0]
        t1 = para1.text if hasattr(para1, 'text') else ""
        t0 = para0.text if hasattr(para0, 'text') else ""
        if t1 in ("MEASURED SURFACE AREA", "SCREEDING & SURFACE PREPARATION",
                  f"PAINTING ({brand_display_name})", "LABOUR", "EQUIPMENT & SUNDRIES"):
            section_rows.append(i)
        elif t1.startswith("Subtotal"):
            subtotal_rows.append(i)
        else:
            data_rows.append(i)
        i += 1

    tbl = Table(rows, colWidths=COL)

    style_cmds = [
        ("FONTNAME",      (0,0), (-1,-1), "DejaVuSans"),
        ("FONTSIZE",      (0,0), (-1,-1), 8.5),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
        # Header row
        ("BACKGROUND",    (0,0), (-1,0), NAVY),
        ("TEXTCOLOR",     (0,0), (-1,0), WHITE),
        # Grand total row
        ("BACKGROUND",    (0,grand_row), (-1,grand_row), NAVY),
        ("TEXTCOLOR",     (0,grand_row), (-1,grand_row), WHITE),
        # Default grid for data area
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#CCCCCC")),
        # Zebra stripes on data rows
    ]

    for idx, r in enumerate(data_rows):
        bg = LIGHT if idx % 2 == 0 else WHITE
        style_cmds.append(("BACKGROUND", (0,r), (-1,r), bg))

    for r in section_rows:
        style_cmds.append(("BACKGROUND", (0,r), (-1,r), MIDBLUE))
        style_cmds.append(("SPAN",       (1,r), (-1,r)))

    for r in subtotal_rows:
        style_cmds.append(("BACKGROUND", (0,r), (-1,r), colors.HexColor("#DDE8F8")))
        style_cmds.append(("SPAN",       (0,r), (2,r)))

    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def _build_comparison_table(comparison_list):
    """Builds the multi-brand comparison table."""
    norm = ParagraphStyle("cn", fontName="DejaVuSans", fontSize=8.5, leading=12)
    bold = ParagraphStyle("cb", fontName="DejaVuSans-Bold", fontSize=8.5, leading=12, textColor=GREEN)
    hdr  = ParagraphStyle("ch", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=WHITE)

    COL = [185, 155, 65, 115]

    rows = [[
        Paragraph("Brand", hdr),
        Paragraph("Representative Product", hdr),
        Paragraph("Drums Needed", ParagraphStyle("chc", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=WHITE, alignment=TA_CENTER)),
        Paragraph("Total Paint Cost", ParagraphStyle("chr", fontName="DejaVuSans-Bold", fontSize=8.5, textColor=WHITE, alignment=TA_RIGHT)),
    ]]

    for item in comparison_list:
        is_default = item.get("is_dealership_default", False)
        label = item["brand"] + (" \u2605 Our Dealership Default" if is_default else "")
        style = bold if is_default else norm
        rows.append([
            Paragraph(label, style),
            Paragraph(f"{item['product_name']} \u2013 {item['description']}", norm),
            Paragraph(str(item["total_units"]), ParagraphStyle("cc", fontName="DejaVuSans", fontSize=8.5, alignment=TA_CENTER)),
            Paragraph(naira(item["total_paint_cost"]), ParagraphStyle("cr", fontName="DejaVuSans-Bold" if is_default else "DejaVuSans", fontSize=8.5, alignment=TA_RIGHT, textColor=GREEN if is_default else colors.black)),
        ])

    tbl = Table(rows, colWidths=COL)
    style_cmds = [
        ("BACKGROUND", (0,0), (-1,0), NAVY),
        ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#CCCCCC")),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
    ]
    for i in range(1, len(rows)):
        is_def = comparison_list[i-1].get("is_dealership_default", False)
        bg = colors.HexColor("#E8F5E9") if is_def else (LIGHT if i % 2 == 0 else WHITE)
        style_cmds.append(("BACKGROUND", (0,i), (-1,i), bg))

    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

def generate_estimate_pdf_customer(
    estimate_dict,
    comparison_list,
    brand_display_name,
    customer_name=None,
    project_address=None,
    quote_number=None,
    output_filename=None,
    soultouch_logo_path=None,
):
    """
    Customer-facing estimate PDF, Soul-Touch / Godtech AI branded.
    Includes the brand comparison table showing all 5 dealership brands.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if output_filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"Estimate_Customer_{ts}.pdf"
    filepath = os.path.join(OUTPUT_DIR, output_filename)

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        topMargin=14*mm, bottomMargin=14*mm, leftMargin=16*mm, rightMargin=16*mm,
    )
    s = _styles()
    elements = []

    # ── Logo
    if soultouch_logo_path and os.path.exists(soultouch_logo_path):
        try:
            img = Image(soultouch_logo_path, width=140*mm, height=39*mm)
            img.hAlign = "CENTER"
            elements.append(img)
            elements.append(Spacer(1, 4))
        except Exception:
            pass
    else:
        elements.append(Paragraph("SOUL-TOUCH PAINTING AND INTERIOR DESIGN LTD", s["h1"]))
        elements.append(Paragraph("Powered by Decor AI &nbsp;&bull;&nbsp; A Godtech AI Service", s["small"]))
        elements.append(Spacer(1, 4))

    elements.append(_divider(RED))
    elements.append(Spacer(1, 6))

    # ── Meta row (company left, quote title right)
    meta = Table([[
        Paragraph("SOUL-TOUCH PAINTING AND INTERIOR DESIGN LTD<br/>Stadium Road by Akenzuwa<br/>08100340872  &nbsp;|&nbsp;  RC8538939", s["normal"]),
        Paragraph(f"<b>PAINTING COST ESTIMATE</b><br/>Date: {datetime.now().strftime('%B %d, %Y')}" +
                  (f"<br/>Ref: {quote_number}" if quote_number else ""), s["right"]),
    ]], colWidths=[260, 260])
    meta.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    elements.append(meta)
    elements.append(Spacer(1, 8))

    # ── Client block
    client_lines = []
    if customer_name:
        client_lines.append(f"<b>Prepared For:</b> {customer_name}")
    if project_address:
        client_lines.append(f"<b>Project:</b> {project_address}")
    if client_lines:
        ct = Table([[Paragraph("<br/>".join(client_lines), s["normal"])]],
                   colWidths=[520],
                   style=[("BOX", (0,0), (-1,-1), 0.5, NAVY),
                          ("BACKGROUND", (0,0), (-1,-1), LIGHT),
                          ("LEFTPADDING", (0,0), (-1,-1), 10),
                          ("TOPPADDING", (0,0), (-1,-1), 7),
                          ("BOTTOMPADDING", (0,0), (-1,-1), 7)])
        elements.append(ct)
        elements.append(Spacer(1, 10))

    # ── Estimate table
    elements.append(_build_estimate_table(estimate_dict, brand_display_name))
    elements.append(Spacer(1, 12))

    # ── Brand comparison
    elements.append(Paragraph("Compare Brands We Work With", s["h2"]))
    elements.append(Paragraph(
        "As an authorised Soul-Touch dealership partner, here is how this same job sits "
        "across the major brands we supply. We recommend Double Design for the best balance "
        "of quality and value at our dealership pricing.",
        s["note"]
    ))
    elements.append(Spacer(1, 6))
    elements.append(_build_comparison_table(comparison_list))
    elements.append(Spacer(1, 14))

    elements.append(_divider(RED))
    elements.append(Paragraph(
        f"<b>Payment Terms:</b> {estimate_dict.get('payment_terms', '50% upfront, 50% on completion.')}  "
        "&nbsp;&bull;&nbsp;  This estimate is valid for 14 days.  "
        "&nbsp;&bull;&nbsp;  Final price may vary slightly after a physical site inspection.",
        s["footer"]
    ))
    elements.append(Paragraph(
        "Soul-Touch Painting and Interior Design Ltd &nbsp;|&nbsp; RC8538939 &nbsp;|&nbsp; "
        "Stadium Road by Akenzuwa &nbsp;|&nbsp; 08100340872 &nbsp;|&nbsp; "
        "Powered by Decor AI (Godtech AI)",
        s["footer"]
    ))

    doc.build(elements)
    return filepath


def generate_estimate_pdf_painter(
    estimate_dict,
    brand_display_name,
    painter_business_name,
    painter_phone,
    painter_address=None,
    customer_name=None,
    project_address=None,
    quote_number=None,
    painter_logo_path=None,
    output_filename=None,
):
    """
    Painter-branded estimate PDF. Uses the painter's own business name and logo.
    No Soul-Touch branding. No brand comparison (painters choose their own supplier).
    A small 'Generated via Decor AI' credit line appears in the footer only.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if output_filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"Estimate_Painter_{ts}.pdf"
    filepath = os.path.join(OUTPUT_DIR, output_filename)

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        topMargin=14*mm, bottomMargin=14*mm, leftMargin=16*mm, rightMargin=16*mm,
    )
    s = _styles()
    elements = []

    # ── Painter logo or placeholder
    if painter_logo_path and os.path.exists(painter_logo_path):
        try:
            img = Image(painter_logo_path, width=100*mm, height=28*mm)
            img.hAlign = "LEFT"
            elements.append(img)
            elements.append(Spacer(1, 4))
        except Exception:
            pass

    elements.append(_divider(GOLD))
    elements.append(Spacer(1, 6))

    # ── Meta row
    addr_parts = [f"<b>{painter_business_name}</b>"]
    if painter_address:
        addr_parts.append(painter_address)
    if painter_phone:
        addr_parts.append(painter_phone)

    meta = Table([[
        Paragraph("<br/>".join(addr_parts), s["normal"]),
        Paragraph(
            f"<b>PAINTING COST ESTIMATE</b><br/>Date: {datetime.now().strftime('%B %d, %Y')}" +
            (f"<br/>Ref: {quote_number}" if quote_number else "") +
            "<br/><font size='7' color='#999999'><i>Generated via Decor AI</i></font>",
            s["right"]
        ),
    ]], colWidths=[260, 260])
    meta.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    elements.append(meta)
    elements.append(Spacer(1, 8))

    # ── Client block
    client_lines = []
    if customer_name:
        client_lines.append(f"<b>Prepared For:</b> {customer_name}")
    if project_address:
        client_lines.append(f"<b>Project:</b> {project_address}")
    if client_lines:
        ct = Table([[Paragraph("<br/>".join(client_lines), s["normal"])]],
                   colWidths=[520],
                   style=[("BOX", (0,0), (-1,-1), 0.5, NAVY),
                          ("BACKGROUND", (0,0), (-1,-1), LIGHT),
                          ("LEFTPADDING", (0,0), (-1,-1), 10),
                          ("TOPPADDING", (0,0), (-1,-1), 7),
                          ("BOTTOMPADDING", (0,0), (-1,-1), 7)])
        elements.append(ct)
        elements.append(Spacer(1, 10))

    # ── Estimate table
    elements.append(_build_estimate_table(estimate_dict, brand_display_name))
    elements.append(Spacer(1, 14))

    elements.append(_divider(GOLD))
    elements.append(Paragraph(
        f"<b>Payment Terms:</b> {estimate_dict.get('payment_terms', '50% upfront, 50% on completion.')}  "
        "&nbsp;&bull;&nbsp;  This estimate is valid for 14 days.  "
        "&nbsp;&bull;&nbsp;  Final price may vary slightly after a physical site inspection.",
        s["footer"]
    ))
    elements.append(Paragraph(
        f"{painter_business_name} &nbsp;|&nbsp; Estimate generated via Decor AI (Godtech AI)",
        s["footer"]
    ))

    doc.build(elements)
    return filepath
