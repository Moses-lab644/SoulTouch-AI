"""
po_generator.py
Generates the Purchase Order PDF that a painter presents at a paint dealer's shop
(self-pickup) or that Godtech AI / Decor AI uses internally to arrange delivery.

This document is the physical/printable proof of the dealership relationship -
it is what unlocks the discount (negotiated separately per dealer, see
discount field placeholder below) and is the trigger for points once an admin
marks it fulfilled via /admin commands.
"""

import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register DejaVu Sans - Helvetica's default glyph set does not include the
# Naira symbol (\u20a6), which renders as a black box otherwise.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FONT_DIR = os.path.join(BASE_DIR, "fonts")

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

NAVY = colors.HexColor("#1B3A6B")
GOLD = colors.HexColor("#B8860B")
LIGHT = colors.HexColor("#EEF3FB")
MIDBLUE = colors.HexColor("#D6E4F7")
GREY = colors.HexColor("#666666")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")


def naira(amount):
    return f"\u20a6{amount:,.2f}"


def generate_purchase_order_pdf(
    po_number,
    painter_business_name,
    painter_phone,
    brand_display_name,
    items,                      # list of {"product": str, "qty": int, "unit_price": float, "line_total": float}
    total_amount,
    fulfillment_method,         # "self_pickup" or "godtech_delivery"
    customer_project_ref=None,
    discount_pct=None,          # None until negotiated per dealer; printed as placeholder if not set
    output_filename=None,
):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if output_filename is None:
        output_filename = f"PO_{po_number}.pdf"
    filepath = os.path.join(OUTPUT_DIR, output_filename)

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontName="DejaVuSans-Bold", fontSize=20, textColor=NAVY, alignment=TA_LEFT, spaceAfter=2)
    sub_style = ParagraphStyle("SubStyle", parent=styles["Normal"], fontName="DejaVuSans", fontSize=9, textColor=GREY, alignment=TA_LEFT)
    section_style = ParagraphStyle("SectionStyle", parent=styles["Normal"], fontName="DejaVuSans-Bold", fontSize=12, textColor=NAVY, spaceBefore=10, spaceAfter=6)
    normal_style = ParagraphStyle("NormalStyle", parent=styles["Normal"], fontName="DejaVuSans", fontSize=10, leading=14)
    right_style = ParagraphStyle("RightStyle", parent=styles["Normal"], fontName="DejaVuSans", fontSize=10, alignment=TA_RIGHT)
    footer_style = ParagraphStyle("FooterStyle", parent=styles["Normal"], fontName="DejaVuSans", fontSize=8, textColor=GREY, alignment=TA_CENTER)
    note_style = ParagraphStyle("NoteStyle", parent=styles["Normal"], fontName="DejaVuSans", fontSize=9, textColor=colors.HexColor("#8a6d00"), backColor=colors.HexColor("#FFF8E1"), borderPadding=6, leading=13)

    elements = []

    # ─── Header ──────────────────────────────────────────────────────────────
    elements.append(Paragraph("DECOR AI", title_style))
    elements.append(Paragraph("A Godtech AI Service &nbsp;|&nbsp; Painting Procurement &amp; Estimation Platform", sub_style))
    elements.append(Spacer(1, 6))
    elements.append(HRFlowable(width="100%", thickness=1.2, color=GOLD, spaceAfter=10))

    # ─── Title + PO meta ─────────────────────────────────────────────────────
    meta_table_data = [
        [Paragraph("<b>PURCHASE ORDER</b>", ParagraphStyle("POTitle", fontSize=15, textColor=colors.HexColor("#C0392B"), fontName="DejaVuSans-Bold")),
         Paragraph(f"PO Number: <b>{po_number}</b><br/>Date: {datetime.now().strftime('%B %d, %Y')}", right_style)],
    ]
    meta_table = Table(meta_table_data, colWidths=[260, 260])
    meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    elements.append(meta_table)
    elements.append(Spacer(1, 10))

    # ─── Parties ─────────────────────────────────────────────────────────────
    party_data = [
        [Paragraph("<b>ISSUED BY:</b><br/>Godtech AI / Decor AI<br/>Abuja, Nigeria<br/>godnwankwo@hotmail.com", normal_style),
         Paragraph(f"<b>ISSUED TO (Painter/Buyer):</b><br/>{painter_business_name}<br/>{painter_phone or '[Phone Not on File]'}", normal_style)],
    ]
    party_table = Table(party_data, colWidths=[260, 260])
    party_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (0, 0), 0.75, NAVY),
        ("BOX", (1, 0), (1, 0), 0.75, NAVY),
        ("INNERGRID", (0,0), (-1,-1), 0, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(party_table)
    elements.append(Spacer(1, 4))

    if customer_project_ref:
        elements.append(Paragraph(f"<b>Project Reference:</b> {customer_project_ref}", normal_style))

    elements.append(Paragraph(f"<b>Dealer / Brand:</b> {brand_display_name}", normal_style))
    elements.append(Spacer(1, 6))

    # ─── Items table ─────────────────────────────────────────────────────────
    elements.append(Paragraph("ORDER ITEMS", section_style))

    table_data = [["S/N", "Product", "Qty", "Unit Price (₦)", "Line Total (₦)"]]
    for idx, item in enumerate(items, start=1):
        table_data.append([
            str(idx),
            item["product"],
            str(item["qty"]),
            naira(item["unit_price"]),
            naira(item["line_total"]),
        ])

    items_table = Table(table_data, colWidths=[30, 230, 40, 110, 110])
    items_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("ALIGN", (3, 0), (4, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 4))

    # Summary table - kept separate from items table to avoid span/overlap issues
    discount_display = f"{discount_pct}%" if discount_pct is not None else "To Be Confirmed With Dealer"
    summary_data = [
        ["Subtotal", naira(total_amount)],
        ["Negotiated Discount", discount_display],
    ]
    summary_table = Table(summary_data, colWidths=[410, 110])
    summary_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, 0), MIDBLUE),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#FFF3CD")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#999999")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (0, -1), 10),
        ("RIGHTPADDING", (1, 0), (1, -1), 10),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 12))

    # ─── Fulfillment instructions ───────────────────────────────────────────
    elements.append(Paragraph("FULFILLMENT METHOD", section_style))
    if fulfillment_method == "self_pickup":
        elements.append(Paragraph(
            "<b>Self-Pickup at Dealer's Shop.</b> Present this Purchase Order at the dealer's shop to "
            "confirm your Decor AI / Godtech AI dealership relationship. Once payment is settled directly "
            "with the dealer, you may collect your order. A transport discount may apply for self-pickup, "
            "subject to confirmation with Decor AI.",
            normal_style
        ))
    else:
        elements.append(Paragraph(
            "<b>Godtech AI Arranged Delivery.</b> This order will be placed and coordinated on your behalf. "
            "Delivery will be arranged once payment is confirmed. You will be notified once your order is "
            "ready for dispatch.",
            normal_style
        ))
    elements.append(Spacer(1, 10))

    # ─── Points note ────────────────────────────────────────────────────────
    elements.append(Paragraph(
        "<b>Decor AI Rewards:</b> Purchases made through this Purchase Order, once confirmed fulfilled, "
        "earn Decor AI Points (1 point per product unit purchased). Accumulated points count toward "
        "referred job opportunities from Godtech AI / Soul-Touch. Points are credited after admin confirmation "
        "of fulfillment, not at the time this PO is issued.",
        note_style
    ))
    elements.append(Spacer(1, 14))

    elements.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#CCCCCC"), spaceAfter=8))
    elements.append(Paragraph(
        "This Purchase Order is issued by Godtech AI / Decor AI as proof of an authorized dealership "
        "purchase request. It is not a tax invoice. Final pricing, discount, and availability are subject "
        "to confirmation with the named dealer at the time of pickup/delivery.",
        footer_style
    ))
    elements.append(Paragraph(
        "Godtech AI | Decor AI Painting Estimator | godnwankwo@hotmail.com | wa.me/+2349072334161",
        footer_style
    ))

    doc.build(elements)
    return filepath
