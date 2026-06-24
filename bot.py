"""
bot.py
Decor AI Telegram Bot — main entry point.

Conversation flows:
  CUSTOMER
    /start → measure (choose: room dimensions OR total area)
    → if dimensions: collect walls one by one
    → choose brand → choose interior + exterior products
    → get name + phone (lead capture)
    → receive estimate PDF + brand comparison

  PAINTER (registered + approved)
    /start → same measure flow
    → choose brand → choose products
    → enter client name + project address
    → choose dealership purchase? (Y/N)
    → if Y: choose self_pickup or delivery
    → receive estimate PDF
    → if PO: receive PO PDF, points note

  PAINTER REGISTRATION
    /register → business_name → phone → address → logo image
    → pending approval (GOD gets notified)

  ADMIN (GOD only)
    /admin → view pending painters, leads, open POs
    → approve painter
    → confirm / fulfill / cancel PO

Environment variables required:
    TELEGRAM_BOT_TOKEN  — bot token from @BotFather
    ADMIN_TELEGRAM_ID   — GOD Nwankwo's Telegram user ID (integer)
    DB_PATH             — optional, defaults to data/bot.db
"""

import os
import sys
import logging
import tempfile
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
# ─── ensure project root is on path ──────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

from utils.db import (
    init_db, upsert_user, get_user, get_painter_profile,
    register_painter, approve_painter, list_pending_painters,
    save_estimate, save_lead, create_purchase_order,
    list_purchase_orders, get_purchase_order,
    confirm_purchase_order, fulfill_purchase_order,
    cancel_purchase_order, get_points_balance, list_leads,
    set_saas_tier,
)
from utils.estimator import build_full_estimate, build_multi_brand_comparison
from utils.estimate_generator import (
    generate_estimate_pdf_customer, generate_estimate_pdf_painter
)
from utils.po_generator import generate_purchase_order_pdf

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("decor_ai_bot")

ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
SOULTOUCH_LOGO = os.path.join(ROOT, "assets", "soultouch_header.jpeg")

# ─── Conversation states ──────────────────────────────────────────────────────
(
    # Measurement flow
    ST_MEASURE_METHOD,
    ST_WALL_INTERIOR,
    ST_WALL_EXTERIOR,
    ST_TOTAL_AREA,
    # Product flow
    ST_CHOOSE_BRAND,
    ST_CHOOSE_INTERIOR_PRODUCT,
    ST_CHOOSE_EXTERIOR_PRODUCT,
    ST_DEEP_COLOUR,
    ST_SCAFFOLD_DAYS,
    ST_LADDER_DAYS,
    # Customer lead capture
    ST_CUSTOMER_NAME,
    ST_CUSTOMER_PHONE,
    ST_PROJECT_ADDRESS,
    # Painter extras
    ST_CLIENT_NAME,
    ST_CLIENT_ADDRESS,
    ST_WANTS_PO,
    ST_FULFILLMENT_METHOD,
    # Subscription pitch response
    ST_SUBSCRIPTION_INTEREST,
    # Registration
    REG_BUSINESS_NAME,
    REG_PHONE,
    REG_ADDRESS,
    REG_LOGO,
    # Admin
    ADM_MENU,
    ADM_PO_ID,
    ADM_PO_ACTION,
    ADM_PAINTER_ID,
) = range(26)

# ─── Brand / product maps (for Telegram keyboard options) ────────────────────
BRANDS = {
    "🎨 Double Design (Our Default)": "double_design",
    "🔵 Berger Paints":               "berger",
    "🟡 Dulux Trade":                 "dulux",
    "🟢 Macnugar Paints":             "macnugar",
    "🟠 Revano Classic":              "revano",
}

# Representative products per brand for quick selection
BRAND_INTERIOR_PRODUCTS = {
    "double_design": [
        ("D.D. B",      "Budget Emulsion"),
        ("D.D. Y",      "Standard Emulsion"),
        ("D.D. D",      "Premium Matt Finish"),
        ("Double Matt", "Ultra Smooth Matt"),
        ("Satin",       "Economy Satin"),
        ("Satin Plus",  "Standard Satin"),
        ("D.D. Silk",   "Soft Sheen Silk"),
    ],
    "berger": [
        ("Superstar Standard Matt",  "Standard Matt"),
        ("Luxol Premium Matt",       "Premium Matt"),
        ("Luxol Premium Satin",      "Premium Satin"),
        ("Luxol Premium Silk",       "Premium Silk"),
    ],
    "dulux": [
        ("Easy Care",    "Easy Care White"),
        ("Vinyl Silk",   "Trade Vinyl Silk"),
    ],
    "macnugar": [
        ("Vinyl Matt",         "Washable Matt"),
        ("Vinyl Softsheen",    "Mid Sheen"),
        ("Luxury Silk Finish", "High Sheen Silk"),
        ("Satin Ultimate",     "Glossy Satin"),
    ],
    "revano": [
        ("Revano Trade Vinyl Matt", "Trade Vinyl Matt"),
        ("Locmeris Premium Matt",   "Locmeris Premium Matt"),
        ("Locmeris Satin",          "Locmeris Satin"),
    ],
}

BRAND_EXTERIOR_PRODUCTS = {
    "double_design": [
        ("D.D. Z",       "Economy Emulsion"),
        ("D.D. X (DDX)", "Standard Super Emulsion"),
        ("Durable-D",    "Premium Weather Shield"),
        ("Double Guard", "Anti-Carbonation Shield"),
    ],
    "berger": [
        ("Superstar Standard Matt", "Standard Exterior Matt"),
        ("Luxol Premium Matt",      "Premium Exterior Matt"),
    ],
    "dulux": [
        ("WSD Smooth Masonry", "Smooth Masonry"),
        ("Easy Care",          "Easy Care Exterior"),
    ],
    "macnugar": [
        ("Weatherproof Matt",    "Anti-Fungal Matt"),
        ("Weatherproof Silk",    "Anti-Fungal Silk"),
        ("Weatherproof Ultratex","Anti-Fungal Ultratex"),
    ],
    "revano": [
        ("Revano Trade Vinyl Matt", "Trade Vinyl Matt"),
        ("Locmeris Weather Mate",   "Weather Mate"),
    ],
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_painter(telegram_id):
    profile = get_painter_profile(telegram_id)
    return profile is not None and profile["approved"] == 1


def kb(options, cols=2):
    """Build a reply keyboard from a list of option strings."""
    rows = [options[i:i+cols] for i in range(0, len(options), cols)]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def brand_keyboard():
    return kb(list(BRANDS.keys()), cols=2)


def product_keyboard(products):
    labels = [f"{p[0]}" for p in products]
    return kb(labels, cols=2)


async def send_pdf(update: Update, filepath: str, caption: str):
    with open(filepath, "rb") as f:
        await update.message.reply_document(
            document=InputFile(f, filename=os.path.basename(filepath)),
            caption=caption,
        )


# ─── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username, user.full_name)
    painter = is_painter(user.id)

    greeting = (
        f"👋 Welcome back, *{user.first_name}*!\n\n"
        if painter
        else f"👋 Welcome to *Decor AI* — the smart painting estimator by SoulTouch AI!\n\n"
    )

    if painter:
        profile = get_painter_profile(user.id)
        pts = get_points_balance(user.id)
        greeting += (
            f"🏢 *{profile['business_name']}*\n"
            f"⭐ Decor AI Points: *{pts}*\n\n"
            "What would you like to do?"
        )
        options = ["📐 New Estimate", "📋 My Points", "ℹ️ Help"]
    else:
        greeting += (
            "I help you estimate the cost of any painting job — interior, exterior, or both.\n\n"
            "I'll ask for your room measurements, then give you a full cost breakdown with a downloadable PDF.\n\n"
            "Are you a *painter* or a *customer*?"
        )
        options = ["I'm a Customer", "I'm a Painter", "ℹ️ Help"]

    await update.message.reply_text(
        greeting,
        parse_mode="Markdown",
        reply_markup=kb(options, cols=2),
    )
    ctx.user_data.clear()
    ctx.user_data["is_painter"] = painter
    return ST_MEASURE_METHOD


# ─── Measurement flow ─────────────────────────────────────────────────────────

async def choose_measure_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "ℹ️ Help":
        await update.message.reply_text(
            "📖 *How Decor AI works*\n\n"
            "1. Tell me the size of the space you want painted.\n"
            "2. Choose your preferred paint brand.\n"
            "3. I'll calculate materials, labour, and equipment costs.\n"
            "4. You'll get a full PDF estimate.\n\n"
            "If you're a registered painter, you can also generate a Purchase Order "
            "to buy paint through our dealership and earn Decor AI Points.\n\n"
            "Type /register to sign up as a painter.",
            parse_mode="Markdown",
        )
        return ST_MEASURE_METHOD

    if text == "I'm a Painter" and not is_painter(update.effective_user.id):
        await update.message.reply_text(
            "To generate painter-branded estimates, you need to register first.\n\n"
            "Type /register to set up your painter profile. It takes about 2 minutes.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    if text in ("📋 My Points",):
        pts = get_points_balance(update.effective_user.id)
        await update.message.reply_text(
            f"⭐ *Your Decor AI Points Balance: {pts}*\n\n"
            "Points are earned per product unit purchased through our dealership "
            "brands (Double Design, Berger, Dulux, Macnugar, Revano).\n\n"
            "Points build toward referred job opportunities from Soul-Touch / SoulTouch AI.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    ctx.user_data["is_painter"] = is_painter(update.effective_user.id)

    await update.message.reply_text(
        "📐 *How do you want to enter measurements?*\n\n"
        "• *Room Dimensions* — give me length × height for each wall and I calculate the area\n"
        "• *Total Area* — you already know the total m² to be painted",
        parse_mode="Markdown",
        reply_markup=kb(["📏 Room Dimensions", "📊 Total Area I Know"], cols=2),
    )
    return ST_WALL_INTERIOR


async def choose_input_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "Room Dimensions" in text:
        ctx.user_data["measure_mode"] = "dimensions"
        ctx.user_data["interior_walls"] = []
        ctx.user_data["exterior_walls"] = []
        await update.message.reply_text(
            "🏠 *Interior Walls*\n\n"
            "Send me each wall as: *length × height* (in metres)\n"
            "Example: `4.5 x 3` or `4.5x3`\n\n"
            "Send one wall at a time. When done, type *done*.\n\n"
            "_Doors and windows? I'll deduct standard allowances automatically._",
            parse_mode="Markdown",
            reply_markup=kb(["done"], cols=1),
        )
        return ST_WALL_INTERIOR
    else:
        ctx.user_data["measure_mode"] = "total"
        await update.message.reply_text(
            "📊 Enter the *total interior area* in m² (or 0 if interior only):\n\n"
            "Example: `180` or `180.5`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ST_TOTAL_AREA


async def collect_interior_walls(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()

    if text == "done":
        walls = ctx.user_data.get("interior_walls", [])
        interior_area = sum(w["l"] * w["h"] for w in walls)
        ctx.user_data["interior_area"] = round(interior_area, 4)
        await update.message.reply_text(
            f"✅ Interior area: *{interior_area:.2f} m²* from {len(walls)} wall(s).\n\n"
            "🏗️ Now let's do *exterior walls*. Same format: `length × height`\n"
            "If there are no exterior walls, type *0*.",
            parse_mode="Markdown",
            reply_markup=kb(["done", "0"], cols=2),
        )
        return ST_WALL_EXTERIOR

    try:
        parts = text.replace("x", " ").replace("×", " ").split()
        l, h = float(parts[0]), float(parts[1])
        ctx.user_data["interior_walls"].append({"l": l, "h": h})
        total_so_far = sum(w["l"] * w["h"] for w in ctx.user_data["interior_walls"])
        await update.message.reply_text(
            f"✅ Wall added: {l}m × {h}m = {l*h:.2f} m²\n"
            f"Running total: {total_so_far:.2f} m²\n\n"
            "Add another wall or type *done*.",
            parse_mode="Markdown",
            reply_markup=kb(["done"], cols=1),
        )
        return ST_WALL_INTERIOR
    except Exception:
        await update.message.reply_text(
            "❌ Couldn't read that. Please use the format: `length x height`\nExample: `4.5 x 3`",
            parse_mode="Markdown",
        )
        return ST_WALL_INTERIOR


async def collect_exterior_walls(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()

    if text in ("done", "0"):
        walls = ctx.user_data.get("exterior_walls", [])
        exterior_area = sum(w["l"] * w["h"] for w in walls)
        ctx.user_data["exterior_area"] = round(exterior_area, 4)
        return await _proceed_to_brand(update, ctx)

    try:
        parts = text.replace("x", " ").replace("×", " ").split()
        l, h = float(parts[0]), float(parts[1])
        ctx.user_data["exterior_walls"].append({"l": l, "h": h})
        total_so_far = sum(w["l"] * w["h"] for w in ctx.user_data["exterior_walls"])
        await update.message.reply_text(
            f"✅ Wall added: {l}m × {h}m = {l*h:.2f} m²\n"
            f"Running total: {total_so_far:.2f} m²\n\n"
            "Add another wall or type *done*.",
            parse_mode="Markdown",
            reply_markup=kb(["done"], cols=1),
        )
        return ST_WALL_EXTERIOR
    except Exception:
        await update.message.reply_text(
            "❌ Couldn't read that. Please use the format: `length x height`\nExample: `5 x 3.2`",
            parse_mode="Markdown",
        )
        return ST_WALL_EXTERIOR


async def collect_total_area(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        interior = float(update.message.text.strip())
        ctx.user_data["interior_area"] = interior
        await update.message.reply_text(
            f"✅ Interior: *{interior:.2f} m²*\n\n"
            "Now enter the *exterior area* in m² (or 0 if none):",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ST_WALL_EXTERIOR  # reuse state for second input
    except Exception:
        await update.message.reply_text("❌ Please enter a number, e.g. `180` or `90.5`", parse_mode="Markdown")
        return ST_TOTAL_AREA


async def collect_exterior_total(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        exterior = float(update.message.text.strip())
        ctx.user_data["exterior_area"] = exterior
        return await _proceed_to_brand(update, ctx)
    except Exception:
        await update.message.reply_text("❌ Please enter a number, e.g. `90` or `0`", parse_mode="Markdown")
        return ST_WALL_EXTERIOR


async def _proceed_to_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ia = ctx.user_data.get("interior_area", 0)
    ea = ctx.user_data.get("exterior_area", 0)
    total = ia + ea

    await update.message.reply_text(
        f"📐 *Measurements confirmed*\n"
        f"Interior: {ia:.2f} m²\n"
        f"Exterior: {ea:.2f} m²\n"
        f"*Total: {total:.2f} m²*\n\n"
        "Now choose a *paint brand*.\n"
        "We carry all 5 brands through our dealership — Double Design is our recommended default.",
        parse_mode="Markdown",
        reply_markup=brand_keyboard(),
    )
    return ST_CHOOSE_BRAND


# ─── Brand + product selection ────────────────────────────────────────────────

async def choose_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    brand_key = BRANDS.get(text)
    if not brand_key:
        await update.message.reply_text("Please choose one of the brands from the keyboard.", reply_markup=brand_keyboard())
        return ST_CHOOSE_BRAND

    ctx.user_data["brand_key"] = brand_key
    ctx.user_data["brand_display"] = text.split(" ", 1)[1] if " " in text else text

    products = BRAND_INTERIOR_PRODUCTS.get(brand_key, [])
    ctx.user_data["interior_products"] = products

    await update.message.reply_text(
        f"🖌 *{text}* selected.\n\nChoose the *interior paint* product:",
        parse_mode="Markdown",
        reply_markup=product_keyboard(products),
    )
    return ST_CHOOSE_INTERIOR_PRODUCT


async def choose_interior_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    products = ctx.user_data.get("interior_products", [])
    match = next((p for p in products if p[0] == text), None)
    if not match:
        await update.message.reply_text("Please pick from the options shown.", reply_markup=product_keyboard(products))
        return ST_CHOOSE_INTERIOR_PRODUCT

    ctx.user_data["interior_product"] = match[0]

    ext_products = BRAND_EXTERIOR_PRODUCTS.get(ctx.user_data["brand_key"], [])
    ctx.user_data["exterior_products"] = ext_products
    ia = ctx.user_data.get("interior_area", 0)
    ea = ctx.user_data.get("exterior_area", 0)

    if ea == 0:
        ctx.user_data["exterior_product"] = ext_products[0][0] if ext_products else match[0]
        return await ask_deep_colour(update, ctx)

    await update.message.reply_text(
        f"✅ Interior: *{match[0]}* — {match[1]}\n\nNow choose the *exterior paint* product:",
        parse_mode="Markdown",
        reply_markup=product_keyboard(ext_products),
    )
    return ST_CHOOSE_EXTERIOR_PRODUCT


async def choose_exterior_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    products = ctx.user_data.get("exterior_products", [])
    match = next((p for p in products if p[0] == text), None)
    if not match:
        await update.message.reply_text("Please pick from the options shown.", reply_markup=product_keyboard(products))
        return ST_CHOOSE_EXTERIOR_PRODUCT

    ctx.user_data["exterior_product"] = match[0]
    return await ask_deep_colour(update, ctx)


async def ask_deep_colour(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎨 Will this job use *deep or special colours*?\n\n"
        "Deep colours incur a 10% mixing surcharge.",
        parse_mode="Markdown",
        reply_markup=kb(["Yes, deep colours", "No, standard colours"], cols=2),
    )
    return ST_DEEP_COLOUR


async def choose_deep_colour(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["deep_colour"] = "yes" in update.message.text.lower()
    await update.message.reply_text(
        "🔧 How many days of *scaffold* rental? (Enter 0 if none)",
        reply_markup=kb(["0", "1", "2", "3", "4", "5"], cols=3),
    )
    return ST_SCAFFOLD_DAYS


async def choose_scaffold(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["scaffold_days"] = int(update.message.text.strip())
    except Exception:
        ctx.user_data["scaffold_days"] = 0
    await update.message.reply_text(
        "🪜 How many days of *ladder* rental? (Enter 0 if none)",
        reply_markup=kb(["0", "1", "2", "3", "4", "5"], cols=3),
    )
    return ST_LADDER_DAYS


async def choose_ladder(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["ladder_days"] = int(update.message.text.strip())
    except Exception:
        ctx.user_data["ladder_days"] = 0

    if ctx.user_data.get("is_painter"):
        await update.message.reply_text(
            "👤 Enter the *client's name* for this estimate:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ST_CLIENT_NAME
    else:
        await update.message.reply_text(
            "📝 Your name please (so we can address your estimate):",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ST_CUSTOMER_NAME


# ─── Customer lead capture ────────────────────────────────────────────────────

async def customer_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["customer_name"] = update.message.text.strip()
    await update.message.reply_text("📞 Your phone number (for follow-up):")
    return ST_CUSTOMER_PHONE


async def customer_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["customer_phone"] = update.message.text.strip()
    await update.message.reply_text("📍 Project address or description (optional — type *skip* to skip):", parse_mode="Markdown")
    return ST_PROJECT_ADDRESS


async def project_address_customer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["project_address"] = "" if text.lower() == "skip" else text
    return await generate_and_send_estimate(update, ctx)


# ─── Painter client details ───────────────────────────────────────────────────

async def client_name_painter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["customer_name"] = update.message.text.strip()
    await update.message.reply_text("📍 Project address:")
    return ST_CLIENT_ADDRESS


async def client_address_painter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["project_address"] = update.message.text.strip()
    await update.message.reply_text(
        "🏪 Would you like to purchase the paint through our *dealership*?\n\n"
        "This generates a Purchase Order you can take to the dealer's shop for a "
        "negotiated discount. You also earn *Decor AI Points* per product purchased.",
        parse_mode="Markdown",
        reply_markup=kb(["Yes, generate a Purchase Order", "No, just the estimate"], cols=1),
    )
    return ST_WANTS_PO


async def wants_po(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if "yes" in text:
        ctx.user_data["wants_po"] = True
        await update.message.reply_text(
            "🚚 Choose fulfillment method:",
            reply_markup=kb(["🏪 Self-Pickup at Dealer's Shop", "🚐 Godtech AI Arranges Delivery"], cols=1),
        )
        return ST_FULFILLMENT_METHOD
    else:
        ctx.user_data["wants_po"] = False
        return await generate_and_send_estimate(update, ctx)


async def fulfillment_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    ctx.user_data["fulfillment"] = "self_pickup" if "Self-Pickup" in text else "godtech_delivery"
    return await generate_and_send_estimate(update, ctx)


# ─── Core generation function ─────────────────────────────────────────────────

async def generate_and_send_estimate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text("⏳ Generating your estimate...", reply_markup=ReplyKeyboardRemove())

    ia   = ctx.user_data.get("interior_area", 0)
    ea   = ctx.user_data.get("exterior_area", 0)
    bk   = ctx.user_data.get("brand_key", "double_design")
    ip   = ctx.user_data.get("interior_product", "D.D. D")
    ep   = ctx.user_data.get("exterior_product", "D.D. X (DDX)")
    deep = ctx.user_data.get("deep_colour", False)
    sc   = ctx.user_data.get("scaffold_days", 0)
    ld   = ctx.user_data.get("ladder_days", 0)
    cname= ctx.user_data.get("customer_name", "")
    phone= ctx.user_data.get("customer_phone", "")
    addr = ctx.user_data.get("project_address", "")

    try:
        estimate = build_full_estimate(
            interior_area_m2=ia, exterior_area_m2=ea,
            brand_key=bk, interior_product_name=ip,
            exterior_product_name=ep, deep_colour=deep,
            scaffold_days=sc, ladder_days=ld,
        )
    except Exception as e:
        log.error("Estimation failed: %s", e)
        await update.message.reply_text(
            "❌ Something went wrong building your estimate. Please try again or contact support."
        )
        return ConversationHandler.END

    from utils.price_database_loader import get_brand_display_name
    brand_display = get_brand_display_name(bk)
    comparison = build_multi_brand_comparison(ia, ea)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    is_painter_user = ctx.user_data.get("is_painter", False)

    try:
        if is_painter_user:
            profile = get_painter_profile(uid)
            pdf_path = generate_estimate_pdf_painter(
                estimate_dict=estimate,
                brand_display_name=brand_display,
                painter_business_name=profile["business_name"],
                painter_phone=profile["business_phone"],
                painter_address=profile.get("business_address"),
                customer_name=cname,
                project_address=addr,
                output_filename=f"Estimate_{uid}_{ts}.pdf",
            )
        else:
            pdf_path = generate_estimate_pdf_customer(
                estimate_dict=estimate,
                comparison_list=comparison,
                brand_display_name=brand_display,
                customer_name=cname,
                project_address=addr,
                soultouch_logo_path=SOULTOUCH_LOGO if os.path.exists(SOULTOUCH_LOGO) else None,
                output_filename=f"Estimate_{uid}_{ts}.pdf",
            )
    except Exception as e:
        log.error("PDF generation failed: %s", e)
        await update.message.reply_text("❌ PDF generation failed. Please try again.")
        return ConversationHandler.END

    # Save estimate to DB
    est_id = save_estimate(
        telegram_id=uid,
        user_type="painter" if is_painter_user else "customer",
        interior_area_m2=ia, exterior_area_m2=ea,
        brand_key=bk, interior_product=ip, exterior_product=ep,
        grand_total=estimate["grand_total"],
        estimate_dict=estimate,
        wants_dealership_purchase=ctx.user_data.get("wants_po", False),
    )
    ctx.user_data["grand_total_for_pitch"] = estimate["grand_total"]

    # Save lead for customers
    if not is_painter_user and (cname or phone):
        lead_id = save_lead(uid, est_id, cname, phone, addr)
        # Notify admin
        if ADMIN_ID:
            try:
                await ctx.bot.send_message(
                    ADMIN_ID,
                    f"🔔 *New Lead*\n"
                    f"Name: {cname or 'Unknown'}\n"
                    f"Phone: {phone or 'Not given'}\n"
                    f"Address: {addr or 'Not given'}\n"
                    f"Total Estimate: ₦{estimate['grand_total']:,.2f}\n"
                    f"Brand: {brand_display}\n"
                    f"Lead ID: {lead_id}",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    # Send the PDF
    grand = estimate["grand_total"]
    caption = (
        f"✅ *Your Estimate is Ready*\n\n"
        f"Grand Total: *₦{grand:,.2f}*\n"
        f"Payment Terms: {estimate.get('payment_terms', '50% upfront, 50% on completion')}\n\n"
        f"This estimate is valid for 14 days. "
        f"Final price may vary after a site inspection."
    )
    await send_pdf(update, pdf_path, caption)

    # ── Purchase Order flow for painters ─────────────────────────────────────
    if is_painter_user and ctx.user_data.get("wants_po"):
        pt = estimate["sections"].get("painting", {})
        items = []
        if pt.get("interior"):
            ip_data = pt["interior"]
            items.append({"product": f"{ip_data['product_name']} — Interior",
                           "qty": ip_data["units_needed"],
                           "unit_price": ip_data["unit_price"],
                           "line_total": ip_data["total_cost"]})
        if pt.get("exterior"):
            ep_data = pt["exterior"]
            items.append({"product": f"{ep_data['product_name']} — Exterior",
                           "qty": ep_data["units_needed"],
                           "unit_price": ep_data["unit_price"],
                           "line_total": ep_data["total_cost"]})

        paint_total = pt.get("subtotal", 0)
        po = create_purchase_order(
            telegram_id=uid, estimate_id=est_id,
            brand_key=bk, items_list=items,
            total_amount=paint_total,
            fulfillment_method=ctx.user_data.get("fulfillment", "self_pickup"),
        )

        po_pdf = generate_purchase_order_pdf(
            po_number=po["po_number"],
            painter_business_name=get_painter_profile(uid)["business_name"],
            painter_phone=get_painter_profile(uid)["business_phone"],
            brand_display_name=brand_display,
            items=items,
            total_amount=paint_total,
            fulfillment_method=ctx.user_data.get("fulfillment", "self_pickup"),
            customer_project_ref=addr or cname or "",
            discount_pct=None,
            output_filename=f"PO_{po['po_number']}.pdf",
        )

        await send_pdf(update, po_pdf,
                       f"🛒 *Purchase Order {po['po_number']}*\n\n"
                       f"Present this at the dealer's shop to confirm your Decor AI "
                       f"dealership relationship.\n\n"
                       f"Points will be credited once Godtech AI confirms fulfillment.")

        # Notify admin of new PO
        if ADMIN_ID:
            try:
                profile = get_painter_profile(uid)
                await ctx.bot.send_message(
                    ADMIN_ID,
                    f"📦 *New Purchase Order*\n"
                    f"PO: {po['po_number']}\n"
                    f"Painter: {profile['business_name']}\n"
                    f"Brand: {brand_display}\n"
                    f"Total: ₦{paint_total:,.2f}\n"
                    f"Method: {ctx.user_data.get('fulfillment', 'self_pickup')}\n\n"
                    f"Use /admin to confirm or fulfill this PO.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    # ── Subscription pitch (customers only, estimate ≥ ₦600,000) ─────────────
    SUBSCRIPTION_THRESHOLD = 600_000
    if not is_painter_user and estimate["grand_total"] >= SUBSCRIPTION_THRESHOLD:
        grand = estimate["grand_total"]
        # Suggest the most appropriate tier based on estimate size
        if grand >= 3_000_000:
            tier_name = "Gold"
            tier_price = "₦380,000"
            tier_desc = "Unlimited minor visits, quarterly repaints, 24/7 emergency response, executive reports"
        elif grand >= 1_500_000:
            tier_name = "Silver"
            tier_price = "₦200,000"
            tier_desc = "4 scheduled visits/year, 1 accent wall repaint, monthly inspection dashboard, account manager"
        else:
            tier_name = "Bronze"
            tier_price = "₦95,000"
            tier_desc = "Bi-monthly inspection, 2 maintenance visits/year, priority 48hr response, trade paint access"

        await update.message.reply_text(
            f"💡 *Before you go — a thought worth ₦{grand:,.0f}*\n\n"
            f"You're about to spend *₦{grand:,.2f}* on a one-off repaint.\n\n"
            f"Most buildings in Nigeria get repainted every 4–6 years — reactively, "
            f"when the damage is already visible and the cost is highest.\n\n"
            f"*Soul-Touch's {tier_name} Care Plan* ({tier_price}/month) changes that:\n"
            f"→ {tier_desc}\n\n"
            f"Your building stays in condition year-round. No surprise repair bills. "
            f"No hunting for contractors. One fixed monthly fee.\n\n"
            f"*Interested in the {tier_name} plan?*\n"
            f"Reply *YES* and GOD Nwankwo will reach out directly to walk you through it.\n\n"
            f"Or type /start to run another estimate.",
            parse_mode="Markdown",
            reply_markup=kb(["Yes, tell me more", "No thanks"], cols=2),
        )
        # Store pitch state so next message can be captured
        ctx.user_data["subscription_pitched"] = True
        ctx.user_data["pitched_tier"] = tier_name
        ctx.user_data["lead_id"] = lead_id if not is_painter_user else None
        return ST_SUBSCRIPTION_INTEREST

    # ── Painter SaaS pitch (painters only, on first use — not yet subscribed) ──
    elif is_painter_user:
        profile = get_painter_profile(uid)
        saas_tier = profile.get("saas_tier", "free")
        if saas_tier == "free":
            await update.message.reply_text(
                f"🚀 *Upgrade to Decor AI Pro*\n\n"
                f"You're currently on the *Free plan* — basic estimates only.\n\n"
                f"*Decor AI Pro* (₦5,000–10,000/month) gives you:\n"
                f"→ Fully branded PDFs with your logo on every estimate\n"
                f"→ Unlimited estimates per month\n"
                f"→ Purchase Orders for dealership discounts on Double Design, Berger, Dulux, Macnugar & Revano\n"
                f"→ Decor AI Points per purchase (building toward premium perks)\n"
                f"→ Client estimate history and records\n\n"
                f"Type /upgrade to learn more, or /start for another estimate.",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await update.message.reply_text(
                "Need another estimate? Type /start to begin again.",
                reply_markup=ReplyKeyboardRemove(),
            )
    else:
        await update.message.reply_text(
            "Need another estimate? Type /start to begin again.",
            reply_markup=ReplyKeyboardRemove(),
        )

    return ConversationHandler.END


# ─── Subscription pitch response ─────────────────────────────────────────────

async def subscription_interest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    tier = ctx.user_data.get("pitched_tier", "Bronze")

    if "yes" in text:
        cname = ctx.user_data.get("customer_name", "")
        phone = ctx.user_data.get("customer_phone", "")
        grand = ctx.user_data.get("estimate", {})

        # Notify admin of subscription interest
        if ADMIN_ID:
            try:
                await ctx.bot.send_message(
                    ADMIN_ID,
                    f"🔥 *Subscription Interest — {tier} Plan*\n\n"
                    f"Client: {cname or 'Unknown'}\n"
                    f"Phone: {phone or 'Not captured'}\n"
                    f"Estimate Total: ₦{ctx.user_data.get('grand_total_for_pitch', 0):,.2f}\n"
                    f"Telegram ID: {update.effective_user.id}\n\n"
                    f"Follow up directly with this client.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        await update.message.reply_text(
            f"✅ *Perfect.*\n\n"
            f"GOD Nwankwo will reach out to you directly to walk you through "
            f"the Soul-Touch *{tier} Care Plan* and answer any questions.\n\n"
            f"In the meantime, your estimate PDF is ready to share with anyone "
            f"who needs to see the full cost breakdown.\n\n"
            f"Type /start whenever you need another estimate.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await update.message.reply_text(
            "No problem. Your estimate PDF is ready whenever you need it.\n\n"
            "Type /start to run another estimate.",
            reply_markup=ReplyKeyboardRemove(),
        )

    return ConversationHandler.END


# ─── /upgrade (painter SaaS upgrade info) ────────────────────────────────────

async def cmd_upgrade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_painter(uid):
        await update.message.reply_text(
            "The Decor AI Pro plan is for registered painters.\n\n"
            "Type /register to set up your painter profile first.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await update.message.reply_text(
        "🚀 *Decor AI Pro — Painter SaaS Plan*\n\n"
        "*What you get:*\n"
        "✅ Unlimited painter-branded estimate PDFs with your logo\n"
        "✅ Purchase Orders for dealership pricing across 5 brands\n"
        "✅ Decor AI Points per product unit purchased\n"
        "✅ Full estimate history\n"
        "✅ Priority support from Godtech AI\n\n"
        "*Pricing:*\n"
        "₦5,000/month — Standard\n"
        "₦10,000/month — Premium (coming soon: client dashboard + multi-user)\n\n"
        "*To subscribe:*\n"
        "Contact GOD Nwankwo directly:\n"
        "📞 +234 907 233 4161 (WhatsApp)\n"
        "📧 godnwankwo@hotmail.com\n\n"
        "Your account will be upgraded within 24 hours of payment.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )


# ─── /register (painter onboarding) ──────────────────────────────────────────

async def cmd_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_painter(uid):
        profile = get_painter_profile(uid)
        await update.message.reply_text(
            f"✅ You're already registered as *{profile['business_name']}*.\n"
            f"Use /start to generate estimates.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🎨 *Painter Registration*\n\n"
        "Register to create painter-branded estimates, earn Decor AI Points, "
        "and access dealership Purchase Orders.\n\n"
        "What's your *business name*?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return REG_BUSINESS_NAME


async def reg_business_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["reg_biz_name"] = update.message.text.strip()
    await update.message.reply_text("📞 Your business phone number:")
    return REG_PHONE


async def reg_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["reg_phone"] = update.message.text.strip()
    await update.message.reply_text("📍 Your business address:")
    return REG_ADDRESS


async def reg_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["reg_address"] = update.message.text.strip()
    await update.message.reply_text(
        "🖼 Send your *business logo* as a photo/image (optional).\n\n"
        "Type *skip* to skip for now (you can add it later).",
        parse_mode="Markdown",
    )
    return REG_LOGO


async def reg_logo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    logo_file_id = None

    if update.message.photo:
        logo_file_id = update.message.photo[-1].file_id
    elif update.message.document and "image" in (update.message.document.mime_type or ""):
        logo_file_id = update.message.document.file_id

    upsert_user(uid, update.effective_user.username, update.effective_user.full_name, user_type="painter")
    register_painter(
        telegram_id=uid,
        business_name=ctx.user_data["reg_biz_name"],
        business_address=ctx.user_data["reg_address"],
        business_phone=ctx.user_data["reg_phone"],
        logo_file_id=logo_file_id,
    )

    await update.message.reply_text(
        f"✅ *Registration submitted!*\n\n"
        f"Business: *{ctx.user_data['reg_biz_name']}*\n"
        f"Phone: {ctx.user_data['reg_phone']}\n\n"
        f"GOD Nwankwo will review and approve your account shortly. "
        f"You'll be notified here once approved.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Notify admin
    if ADMIN_ID:
        try:
            await ctx.bot.send_message(
                ADMIN_ID,
                f"🆕 *New Painter Registration*\n"
                f"Name: {update.effective_user.full_name}\n"
                f"Business: {ctx.user_data['reg_biz_name']}\n"
                f"Phone: {ctx.user_data['reg_phone']}\n"
                f"Address: {ctx.user_data['reg_address']}\n"
                f"Telegram ID: {uid}\n\n"
                f"Use `/admin approve {uid}` to approve.",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    return ConversationHandler.END


# ─── /admin ───────────────────────────────────────────────────────────────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🔒 Admin access only.")
        return

    # Support inline commands: /admin approve 123456, /admin fulfill 42, etc.
    args = ctx.args or []
    if args:
        action = args[0].lower()

        if action == "approve" and len(args) == 2:
            try:
                tid = int(args[1])
                approve_painter(tid, approved=True)
                await update.message.reply_text(f"✅ Painter {tid} approved.")
                try:
                    await ctx.bot.send_message(
                        tid,
                        "🎉 *Your Decor AI painter account is approved!*\n\n"
                        "Type /start to begin generating painter-branded estimates "
                        "and Purchase Orders.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
            return

        if action == "reject" and len(args) == 2:
            try:
                tid = int(args[1])
                approve_painter(tid, approved=False)
                await update.message.reply_text(f"❌ Painter {tid} rejected.")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
            return

        if action == "confirm" and len(args) == 2:
            try:
                po_id = int(args[1])
                confirm_purchase_order(po_id, admin_notes="Confirmed via Telegram admin")
                po = get_purchase_order(po_id)
                await update.message.reply_text(f"✅ PO {po['po_number']} confirmed.")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
            return

        if action == "fulfill" and len(args) == 2:
            try:
                po_id = int(args[1])
                points = fulfill_purchase_order(po_id, points_per_item=1,
                                                admin_notes="Fulfilled via Telegram admin")
                po = get_purchase_order(po_id)
                await update.message.reply_text(
                    f"✅ PO {po['po_number']} fulfilled.\n"
                    f"⭐ {points} Decor AI Points awarded to painter {po['telegram_id']}."
                )
                try:
                    await ctx.bot.send_message(
                        po["telegram_id"],
                        f"🎉 *Purchase Order {po['po_number']} Fulfilled!*\n\n"
                        f"⭐ *{points} Decor AI Points* have been added to your account.\n\n"
                        f"Type /start to check your points balance.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
            return

        if action == "cancel" and len(args) == 2:
            try:
                po_id = int(args[1])
                cancel_purchase_order(po_id, admin_notes="Cancelled via Telegram admin")
                po = get_purchase_order(po_id)
                await update.message.reply_text(f"❌ PO {po['po_number']} cancelled.")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
            return

        # /admin upgrade 123456 standard  OR  /admin upgrade 123456 premium
        if action == "upgrade" and len(args) >= 2:
            try:
                tid = int(args[1])
                tier = args[2].lower() if len(args) >= 3 else "standard"
                if tier not in ("free", "standard", "premium"):
                    await update.message.reply_text("Tier must be: free, standard, or premium")
                    return
                set_saas_tier(tid, tier)
                await update.message.reply_text(f"✅ Painter {tid} upgraded to *{tier}* SaaS tier.", parse_mode="Markdown")
                try:
                    tier_name = "Standard" if tier == "standard" else "Premium"
                    await ctx.bot.send_message(
                        tid,
                        f"🎉 *Your Decor AI account has been upgraded to {tier_name}!*\n\n"
                        f"You now have full access to:\n"
                        f"→ Branded PDFs with your logo\n"
                        f"→ Purchase Orders for dealership pricing\n"
                        f"→ Decor AI Points on every purchase\n\n"
                        f"Type /start to begin generating professional estimates.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")
            return

    # ── Default: show summary dashboard ──────────────────────────────────────
    pending = list_pending_painters()
    open_pos = list_purchase_orders(status="pending")
    confirmed_pos = list_purchase_orders(status="confirmed")
    new_leads = list_leads(status="new")

    msg = (
        "🛠 *Decor AI Admin Dashboard*\n\n"
        f"👤 Pending painter approvals: *{len(pending)}*\n"
        f"📦 Open Purchase Orders: *{len(open_pos)}*\n"
        f"✅ Confirmed POs (awaiting fulfillment): *{len(confirmed_pos)}*\n"
        f"📋 New leads: *{len(new_leads)}*\n\n"
    )

    if pending:
        msg += "*Pending Painters:*\n"
        for p in pending:
            msg += f"• {p['business_name']} (ID: `{p['telegram_id']}`)\n"
            msg += f"  → `/admin approve {p['telegram_id']}`\n"
        msg += "\n"

    if open_pos:
        msg += "*Open Purchase Orders:*\n"
        for po in open_pos[:5]:
            msg += f"• {po['po_number']} — ₦{po['total_amount']:,.0f}\n"
            msg += f"  → `/admin confirm {po['po_id']}` | `/admin cancel {po['po_id']}`\n"
        msg += "\n"

    if confirmed_pos:
        msg += "*Confirmed POs (ready to fulfill):*\n"
        for po in confirmed_pos[:5]:
            msg += f"• {po['po_number']} — ₦{po['total_amount']:,.0f}\n"
            msg += f"  → `/admin fulfill {po['po_id']}`\n"
        msg += "\n"

    if new_leads:
        msg += "*New Leads:*\n"
        for lead in new_leads[:5]:
            msg += f"• {lead['customer_name'] or 'Unknown'} — {lead['customer_phone'] or 'No phone'}\n"
        msg += "\n"

    msg += "_Use `/admin [action] [id]` to act on any item above._"
    await update.message.reply_text(msg, parse_mode="Markdown")


# ─── Fallback ─────────────────────────────────────────────────────────────────

async def fallback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "I didn't understand that. Type /start to begin a new estimate, "
        "or /register to sign up as a painter."
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Type /start to begin again.", reply_markup=ReplyKeyboardRemove())
    ctx.user_data.clear()
    return ConversationHandler.END


# ─── App assembly ─────────────────────────────────────────────────────────────

def build_app():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    init_db()

    app = ApplicationBuilder().token(token).build()

    # Main estimation conversation
    main_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ST_MEASURE_METHOD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_measure_method),
            ],
            ST_WALL_INTERIOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_input_type),
            ],
            ST_TOTAL_AREA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_total_area),
            ],
            ST_WALL_EXTERIOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_exterior_total),
            ],
            ST_CHOOSE_BRAND: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_brand),
            ],
            ST_CHOOSE_INTERIOR_PRODUCT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_interior_product),
            ],
            ST_CHOOSE_EXTERIOR_PRODUCT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_exterior_product),
            ],
            ST_DEEP_COLOUR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_deep_colour),
            ],
            ST_SCAFFOLD_DAYS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_scaffold),
            ],
            ST_LADDER_DAYS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_ladder),
            ],
            ST_CUSTOMER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, customer_name),
            ],
            ST_CUSTOMER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, customer_phone),
            ],
            ST_PROJECT_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, project_address_customer),
            ],
            ST_CLIENT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_name_painter),
            ],
            ST_CLIENT_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_address_painter),
            ],
            ST_WANTS_PO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wants_po),
            ],
            ST_FULFILLMENT_METHOD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fulfillment_method),
            ],
            ST_SUBSCRIPTION_INTEREST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, subscription_interest),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            MessageHandler(filters.TEXT & ~filters.COMMAND, fallback),
        ],
        allow_reentry=True,
    )

    # Painter registration conversation
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("register", cmd_register)],
        states={
            REG_BUSINESS_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_business_name)],
            REG_PHONE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone)],
            REG_ADDRESS:       [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_address)],
            REG_LOGO:          [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, reg_logo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_logo),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )

    app.add_handler(main_conv)
    app.add_handler(reg_conv)
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("upgrade", cmd_upgrade))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))

    return app


if __name__ == "__main__":
    app = build_app()
    log.info("Decor AI bot starting...")
    app.run_polling()
