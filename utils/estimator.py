"""
estimator.py
Core painting cost estimation engine for the Soul-Touch / Godtech AI Painting Estimator Bot.

Formulas encoded here are derived directly from the Soul-Touch invoices and quotations
prepared with GOD Nwankwo:

1. SURFACE AREA
   - Interior area + Exterior area = Total area (m^2)
   - User can supply total area directly, OR supply room dimensions
     (length x height per wall, minus door/window deductions) and the bot sums it.

2. SCREEDING / SURFACE PREPARATION
   - Stabilizing solution: fixed reference qty observed in source data was 10 drums
     for a job with ~1,970.92 m^2 total area. This implies an approx coverage of:
         1 drum stabilizing solution ≈ 197 m^2
     (1,970.9201 / 10 = 197.09). This is an assumption pending GOD's confirmation,
     flagged clearly in output.
   - Putty: Total area (m^2) ÷ 14 = number of 20L drums of putty required (rounded UP,
     since you cannot buy a fraction of a drum).
         drums_of_putty = ceil(total_area_m2 / 14)

3. PAINTING (paint quantity)
   - Source quotation: 1,970.9201 m^2 total area required:
         27 drums interior paint + 22 drums exterior paint = 49 drums for ~1,970.92 m^2
     This implies an approx combined coverage of:
         1 drum (20L) ≈ 40.22 m^2 per coat (1,970.9201 / 49 ≈ 40.22)
     This is treated as a single-coat coverage assumption per drum, used as the
     default unless overridden. Flagged for GOD's confirmation since it does not
     match standard published coverage rates for emulsion paints (industry standard
     is closer to 60-80 m^2 per 20L drum per coat for smooth surfaces) -- the lower
     number in the source data likely reflects rough/textured surfaces, multiple coats,
     or a more conservative estimate. GOD should confirm and the bot allows override.

4. LABOUR
   - Painting, screeding, and surface preparation labour: ₦1,500 per m^2 of total area.
         labour_cost = total_area_m2 * 1500

5. SUNDRIES
   - Flat allowance observed in source quotations: ₦45,000 - ₦55,000 covering
     transport, covering sheet, masking tape, abrasive paper (NOT scaffold/ladder).
   - Scaffold and ladder are priced separately, per day, when required.

6. GLOSS PAINT (kerbs, protectors, doors, gates)
   - Estimated separately as a fixed allowance unless user specifies exact gallons.

7. PAYMENT TERMS
   - Default split: 50% upfront, 50% on completion (per Godtech AI / Soul-Touch
     standard terms), unless a different schedule is already agreed.

All formula constants live in CONSTANTS below so GOD can tune them without touching
the calculation logic.
"""

import math
import json
import os

CONSTANTS = {
    "putty_coverage_m2_per_drum": 14.0,          # m^2 per 20L drum of putty
    "stabilizing_solution_coverage_m2_per_drum": 197.1,  # m^2 per drum, calibrated to match source quotation (1970.9201 / 10 drums = 197.09)
    "paint_coverage_m2_per_drum_20L_interior": 50.74,   # m^2 per 20L drum, interior (from source: 1370.1158/27 drums)
    "paint_coverage_m2_per_drum_20L_exterior": 27.31,   # m^2 per 20L drum, exterior (from source: 600.8043/22 drums) - lower due to rough/textured surfaces and weather coats
    "labour_rate_per_m2": 1500.0,                 # NGN per m^2 - painting, screeding, surface prep
    "sundry_allowance_default": 50000.0,          # NGN flat - transport, covering sheet, masking tape, abrasive paper
    "scaffold_rate_per_day": 12000.0,             # NGN per day
    "ladder_rate_per_day": 5000.0,                # NGN per day
    "deep_colour_mixing_pct": 10.0,               # % surcharge for deep/custom colour mixing (Soul-Touch standard)
    "default_putty_brand": "double_design",
    "default_putty_product_key": ("surface_prep_screeding_putty", 0),  # Doublie 1, ₦21,000/20L drum
    "default_stabilizing_note": "Stabilizing solution pricing observed at ₦37,500/drum in source quotation. Not yet matched to a specific catalogue SKU; treat as a fixed line item until GOD confirms supplier/brand.",
    "payment_terms_default": "50% upfront, 50% on completion",
}

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "price_database.json")


def load_price_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ceil_drums(area_m2, coverage_per_drum):
    """Round UP to nearest whole drum - cannot buy partial drums."""
    if coverage_per_drum <= 0:
        return 0
    return math.ceil(area_m2 / coverage_per_drum)


def calc_area_from_dimensions(walls, deductions=None):
    """
    walls: list of dicts like [{"length_m": 4.5, "height_m": 3.0}, ...]
    deductions: list of dicts like [{"width_m": 1.0, "height_m": 2.1, "type": "door"}, ...]
    Returns total wall area in m^2 after deductions.
    """
    gross = sum(w["length_m"] * w["height_m"] for w in walls)
    deducted = 0.0
    if deductions:
        deducted = sum(d["width_m"] * d["height_m"] for d in deductions)
    net = max(gross - deducted, 0.0)
    return round(net, 4)


def estimate_putty(total_area_m2, brand="double_design"):
    db = load_price_db()
    drums = ceil_drums(total_area_m2, CONSTANTS["putty_coverage_m2_per_drum"])
    brand_data = db["brands"].get(brand, db["brands"]["double_design"])
    putty_product = None
    for line_key, line in brand_data["lines"].items():
        if "putty" in line_key.lower() or "screeding" in line_key.lower():
            for p in line["products"]:
                if "Doublie 1" in p["item"] or "exterior" in p.get("description", "").lower():
                    putty_product = p
                    break
        if putty_product:
            break
    unit_price = 21000.00  # fallback default (Doublie 1, 20L)
    product_name = "Putty (Surface Preparation)"
    if putty_product:
        unit_price = putty_product["pack_sizes"].get("20L", unit_price)
        product_name = putty_product["item"]
    return {
        "drums_needed": drums,
        "unit_price": unit_price,
        "total_cost": round(drums * unit_price, 2),
        "product_name": product_name,
        "formula_note": f"{total_area_m2} m\u00b2 \u00f7 {CONSTANTS['putty_coverage_m2_per_drum']} m\u00b2/drum, rounded up = {drums} drums",
    }


def estimate_stabilizing_solution(total_area_m2):
    drums = ceil_drums(total_area_m2, CONSTANTS["stabilizing_solution_coverage_m2_per_drum"])
    unit_price = 37500.00
    return {
        "drums_needed": drums,
        "unit_price": unit_price,
        "total_cost": round(drums * unit_price, 2),
        "product_name": "Stabilizing Solution",
        "formula_note": f"{total_area_m2} m\u00b2 \u00f7 {CONSTANTS['stabilizing_solution_coverage_m2_per_drum']} m\u00b2/drum (assumption), rounded up = {drums} drums",
    }


def get_paint_options(brand_key, db=None):
    """Return a flat list of {item, description, category, pack_sizes} for a brand."""
    if db is None:
        db = load_price_db()
    brand = db["brands"].get(brand_key)
    if not brand:
        return []
    flat = []
    for line_key, line in brand["lines"].items():
        for p in line["products"]:
            flat.append({
                "line_key": line_key,
                "category": line["category"],
                "item": p["item"],
                "description": p.get("description", ""),
                "pack_sizes": p["pack_sizes"],
            })
    return flat


def get_unit_price(pack_sizes_dict, pack_size_key, vat_inclusive=True):
    """
    pack_sizes_dict can hold either a plain float (Double Design, Macnugar, Revano)
    or a dict with excl_vat/incl_vat (Berger, Dulux).
    Some brands (Berger, Double Design industrial lines) use prefixed keys like
    'PAIL_20L' or 'GALLON_4L' instead of plain '20L'/'4L'. This function tries
    the exact key first, then falls back to matching by suffix.
    """
    val = pack_sizes_dict.get(pack_size_key)
    if val is None:
        # Try suffix match, e.g. "20L" matches "PAIL_20L" or "GALLON_4L" style keys
        for k, v in pack_sizes_dict.items():
            if k.endswith(pack_size_key) or k == pack_size_key:
                val = v
                break
    if val is None:
        return None
    if isinstance(val, dict):
        return val["incl_vat"] if vat_inclusive else val["excl_vat"]
    return val


def estimate_paint(total_area_m2, brand_key, item_name, pack_size_key="20L", vat_inclusive=True, db=None, surface_type="interior"):
    """
    Estimate paint drums/cans needed and cost for a given brand + product + pack size.
    surface_type: "interior" or "exterior" - determines which coverage assumption to use,
    since source data shows exterior surfaces consume more paint per m^2 (rougher,
    weather-coated) than interior surfaces.
    """
    if db is None:
        db = load_price_db()
    options = get_paint_options(brand_key, db)
    match = next((o for o in options if o["item"] == item_name), None)
    if not match:
        return None

    unit_price = get_unit_price(match["pack_sizes"], pack_size_key, vat_inclusive)
    if unit_price is None:
        return None

    # Pack size in litres, used to scale the m2/drum coverage assumption
    pack_litres_map = {"20L": 20.0, "10L": 10.0, "5L": 5.0, "4L": 4.0, "2.5L": 2.5, "1L": 1.0}
    pack_litres = pack_litres_map.get(pack_size_key, 20.0)
    base_coverage = (
        CONSTANTS["paint_coverage_m2_per_drum_20L_interior"]
        if surface_type == "interior"
        else CONSTANTS["paint_coverage_m2_per_drum_20L_exterior"]
    )
    coverage_per_unit = base_coverage * (pack_litres / 20.0)

    units_needed = ceil_drums(total_area_m2, coverage_per_unit)

    return {
        "brand": db["brands"][brand_key]["display_name"],
        "product_name": match["item"],
        "description": match["description"],
        "pack_size": pack_size_key,
        "surface_type": surface_type,
        "units_needed": units_needed,
        "unit_price": unit_price,
        "total_cost": round(units_needed * unit_price, 2),
        "formula_note": f"{total_area_m2} m\u00b2 \u00f7 {coverage_per_unit:.2f} m\u00b2/{pack_size_key} ({surface_type} assumption), rounded up = {units_needed} units",
    }


def estimate_labour(total_area_m2):
    cost = round(total_area_m2 * CONSTANTS["labour_rate_per_m2"], 2)
    return {
        "total_cost": cost,
        "formula_note": f"{total_area_m2} m\u00b2 \u00d7 \u20a6{CONSTANTS['labour_rate_per_m2']:.2f}/m\u00b2 = \u20a6{cost:,.2f}",
    }


def estimate_sundries(custom_amount=None):
    amount = custom_amount if custom_amount is not None else CONSTANTS["sundry_allowance_default"]
    return {
        "total_cost": amount,
        "formula_note": "Flat allowance covering transport, covering sheet, masking tape, abrasive paper (excludes scaffold/ladder).",
    }


def estimate_equipment_rental(scaffold_days=0, ladder_days=0):
    scaffold_cost = scaffold_days * CONSTANTS["scaffold_rate_per_day"]
    ladder_cost = ladder_days * CONSTANTS["ladder_rate_per_day"]
    return {
        "scaffold_cost": scaffold_cost,
        "ladder_cost": ladder_cost,
        "total_cost": scaffold_cost + ladder_cost,
        "formula_note": f"Scaffold: {scaffold_days} day(s) \u00d7 \u20a6{CONSTANTS['scaffold_rate_per_day']:,.2f} | Ladder: {ladder_days} day(s) \u00d7 \u20a6{CONSTANTS['ladder_rate_per_day']:,.2f}",
    }


def build_full_estimate(
    interior_area_m2,
    exterior_area_m2,
    brand_key,
    interior_product_name,
    exterior_product_name,
    pack_size_key="20L",
    deep_colour=False,
    scaffold_days=0,
    ladder_days=0,
    sundry_override=None,
    include_screeding=True,
    vat_inclusive=True,
):
    """
    Master function that assembles a complete estimate, mirroring the structure
    of the Soul-Touch quotations (Sections: Surface Area, Screeding, Painting, Labour,
    Equipment, Sundries, Grand Total).
    """
    db = load_price_db()
    total_area = round(interior_area_m2 + exterior_area_m2, 4)

    result = {
        "interior_area_m2": interior_area_m2,
        "exterior_area_m2": exterior_area_m2,
        "total_area_m2": total_area,
        "brand": db["brands"][brand_key]["display_name"],
        "sections": {},
    }

    # 1. Screeding (putty + stabilizing solution)
    if include_screeding:
        putty = estimate_putty(total_area, brand="double_design")  # putty always from Double Design (Soul-Touch's own)
        stabilizing = estimate_stabilizing_solution(total_area)
        result["sections"]["screeding"] = {
            "putty": putty,
            "stabilizing_solution": stabilizing,
            "subtotal": round(putty["total_cost"] + stabilizing["total_cost"], 2),
        }

    # 2. Painting (interior + exterior, chosen brand)
    interior_paint = estimate_paint(interior_area_m2, brand_key, interior_product_name, pack_size_key, vat_inclusive, db, surface_type="interior")
    exterior_paint = estimate_paint(exterior_area_m2, brand_key, exterior_product_name, pack_size_key, vat_inclusive, db, surface_type="exterior")

    painting_subtotal = 0.0
    if interior_paint:
        painting_subtotal += interior_paint["total_cost"]
    if exterior_paint:
        painting_subtotal += exterior_paint["total_cost"]

    # Deep colour surcharge (10% per Soul-Touch standard mixing charge)
    deep_colour_charge = 0.0
    if deep_colour:
        deep_colour_charge = round(painting_subtotal * (CONSTANTS["deep_colour_mixing_pct"] / 100), 2)
        painting_subtotal += deep_colour_charge

    result["sections"]["painting"] = {
        "interior": interior_paint,
        "exterior": exterior_paint,
        "deep_colour_charge": deep_colour_charge,
        "subtotal": round(painting_subtotal, 2),
    }

    # 3. Labour
    labour = estimate_labour(total_area)
    result["sections"]["labour"] = labour

    # 4. Equipment rental
    equipment = estimate_equipment_rental(scaffold_days, ladder_days)
    result["sections"]["equipment"] = equipment

    # 5. Sundries
    sundries = estimate_sundries(sundry_override)
    result["sections"]["sundries"] = sundries

    # Grand total
    grand_total = 0.0
    if include_screeding:
        grand_total += result["sections"]["screeding"]["subtotal"]
    grand_total += result["sections"]["painting"]["subtotal"]
    grand_total += result["sections"]["labour"]["total_cost"]
    grand_total += result["sections"]["equipment"]["total_cost"]
    grand_total += result["sections"]["sundries"]["total_cost"]

    result["grand_total"] = round(grand_total, 2)
    result["payment_terms"] = CONSTANTS["payment_terms_default"]

    return result


def build_multi_brand_comparison(
    interior_area_m2,
    exterior_area_m2,
    pack_size_key="20L",
):
    """
    Builds a side-by-side comparison across all 5 brands for the SAME area,
    using each brand's standard/equivalent emulsion product, so the customer
    can see relative cost before picking a dealership brand.
    Interior and exterior areas are costed separately using their respective
    coverage assumptions, then summed, mirroring build_full_estimate.
    NOTE: This is a simplified comparison using each brand's most common
    standard interior emulsion/matt product as a stand-in for both interior
    and exterior costing. Exact product matching across brands is approximate
    since product names/tiers differ. GOD should review product selection per
    brand before this is shown to customers at scale.
    """
    db = load_price_db()
    total_area = round(interior_area_m2 + exterior_area_m2, 4)

    # Representative "standard interior emulsion" product per brand (best-effort match)
    representative_products = {
        "double_design": "D.D. D",                       # Premium Matt Finish
        "berger": "Luxol Premium Matt",                   # White tier
        "dulux": "Easy Care",                              # White tier
        "macnugar": "Vinyl Matt",                          # Brilliant White & Light Colours
        "revano": "Revano Trade Vinyl Matt",
    }

    comparison = []
    for brand_key, product_name in representative_products.items():
        options = get_paint_options(brand_key, db)
        match = next((o for o in options if o["item"] == product_name), None)
        if not match:
            continue

        chosen_pack = pack_size_key
        unit_price = get_unit_price(match["pack_sizes"], chosen_pack, vat_inclusive=True)
        if unit_price is None:
            for alt in ["20L", "5L", "4L"]:
                unit_price = get_unit_price(match["pack_sizes"], alt, vat_inclusive=True)
                if unit_price is not None:
                    chosen_pack = alt
                    break
        if unit_price is None:
            continue

        pack_litres_map = {"20L": 20.0, "10L": 10.0, "5L": 5.0, "4L": 4.0, "2.5L": 2.5, "1L": 1.0}
        pack_litres = pack_litres_map.get(chosen_pack, 20.0)

        interior_coverage = CONSTANTS["paint_coverage_m2_per_drum_20L_interior"] * (pack_litres / 20.0)
        exterior_coverage = CONSTANTS["paint_coverage_m2_per_drum_20L_exterior"] * (pack_litres / 20.0)

        interior_units = ceil_drums(interior_area_m2, interior_coverage) if interior_area_m2 > 0 else 0
        exterior_units = ceil_drums(exterior_area_m2, exterior_coverage) if exterior_area_m2 > 0 else 0
        total_units = interior_units + exterior_units

        comparison.append({
            "brand": db["brands"][brand_key]["display_name"],
            "brand_key": brand_key,
            "product_name": match["item"],
            "description": match["description"],
            "pack_size": chosen_pack,
            "interior_units": interior_units,
            "exterior_units": exterior_units,
            "total_units": total_units,
            "unit_price": unit_price,
            "total_paint_cost": round(total_units * unit_price, 2),
            "is_dealership_default": db["brands"][brand_key].get("is_dealership_default", False),
        })

    comparison.sort(key=lambda x: x["total_paint_cost"])
    return comparison
