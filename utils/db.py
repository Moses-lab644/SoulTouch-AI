"""
db.py
Database layer for the Soul-Touch / SoulTouch AI Painting Estimator Bot.

Uses SQLite for simplicity at launch (per agreed decision). Schema is designed
so migration to Postgres later is straightforward if/when scale demands it -
all queries go through this module, nothing else touches the DB file directly.
"""

import sqlite3
import os
import json
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "bot.db")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ─── Users (could be a Painter or a plain Customer) ──────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            user_type TEXT NOT NULL DEFAULT 'customer',  -- 'customer' or 'painter'
            phone TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # ─── Painter Profiles (extra info, only for user_type = 'painter') ──────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS painter_profiles (
            telegram_id INTEGER PRIMARY KEY,
            business_name TEXT NOT NULL,
            business_address TEXT,
            business_phone TEXT,
            logo_file_id TEXT,
            registered_at TEXT NOT NULL,
            approved INTEGER NOT NULL DEFAULT 0,
            total_points INTEGER NOT NULL DEFAULT 0,
            saas_tier TEXT NOT NULL DEFAULT 'free',
            saas_since TEXT,
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        )
    """)

    # ─── Estimates (every estimate generated, by anyone) ─────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS estimates (
            estimate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            user_type TEXT NOT NULL,             -- snapshot of user_type at time of estimate
            interior_area_m2 REAL NOT NULL,
            exterior_area_m2 REAL NOT NULL,
            brand_key TEXT NOT NULL,
            interior_product TEXT,
            exterior_product TEXT,
            grand_total REAL NOT NULL,
            estimate_json TEXT NOT NULL,         -- full JSON dump of build_full_estimate() output
            wants_dealership_purchase INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        )
    """)

    # ─── Leads (customer contact captured at end of estimate, for follow-up) ─
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            estimate_id INTEGER,
            customer_name TEXT,
            customer_phone TEXT,
            project_address TEXT,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'new',   -- new, contacted, won, lost
            created_at TEXT NOT NULL,
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
            FOREIGN KEY (estimate_id) REFERENCES estimates(estimate_id)
        )
    """)

    # ─── Purchase Orders (dealership purchase requests from painters) ───────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number TEXT UNIQUE NOT NULL,       -- e.g. GTA-PO-000123
            telegram_id INTEGER NOT NULL,          -- painter who requested it
            estimate_id INTEGER,
            brand_key TEXT NOT NULL,
            items_json TEXT NOT NULL,              -- list of {product, qty, unit_price, line_total}
            total_amount REAL NOT NULL,
            fulfillment_method TEXT,               -- 'self_pickup' or 'godtech_delivery'
            status TEXT NOT NULL DEFAULT 'pending', -- pending, confirmed, fulfilled, cancelled
            points_awarded INTEGER NOT NULL DEFAULT 0,
            admin_notes TEXT,
            created_at TEXT NOT NULL,
            fulfilled_at TEXT,
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
            FOREIGN KEY (estimate_id) REFERENCES estimates(estimate_id)
        )
    """)

    # ─── Points Ledger (audit trail of every point movement) ────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS points_ledger (
            ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            po_id INTEGER,
            points_change INTEGER NOT NULL,       -- positive = earned, negative = redeemed
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
            FOREIGN KEY (po_id) REFERENCES purchase_orders(po_id)
        )
    """)

    conn.commit()
    conn.close()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now():
    return datetime.utcnow().isoformat()


# ─── User functions ──────────────────────────────────────────────────────────

def upsert_user(telegram_id, username, full_name, user_type=None, phone=None):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET username = ?, full_name = ? WHERE telegram_id = ?",
                (username, full_name, telegram_id),
            )
            if user_type:
                conn.execute("UPDATE users SET user_type = ? WHERE telegram_id = ?", (user_type, telegram_id))
            if phone:
                conn.execute("UPDATE users SET phone = ? WHERE telegram_id = ?", (phone, telegram_id))
        else:
            conn.execute(
                "INSERT INTO users (telegram_id, username, full_name, user_type, phone, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (telegram_id, username, full_name, user_type or "customer", phone, now()),
            )


def get_user(telegram_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return dict(row) if row else None


def set_user_type(telegram_id, user_type):
    with get_conn() as conn:
        conn.execute("UPDATE users SET user_type = ? WHERE telegram_id = ?", (user_type, telegram_id))


# ─── Painter profile functions ───────────────────────────────────────────────

def register_painter(telegram_id, business_name, business_address, business_phone, logo_file_id=None):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM painter_profiles WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if existing:
            conn.execute(
                """UPDATE painter_profiles SET business_name=?, business_address=?, business_phone=?, logo_file_id=?
                   WHERE telegram_id=?""",
                (business_name, business_address, business_phone, logo_file_id, telegram_id),
            )
        else:
            conn.execute(
                """INSERT INTO painter_profiles
                   (telegram_id, business_name, business_address, business_phone, logo_file_id, registered_at, approved, total_points)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 0)""",
                (telegram_id, business_name, business_address, business_phone, logo_file_id, now()),
            )
        conn.execute("UPDATE users SET user_type = 'painter' WHERE telegram_id = ?", (telegram_id,))


def get_painter_profile(telegram_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM painter_profiles WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return dict(row) if row else None


def approve_painter(telegram_id, approved=True):
    with get_conn() as conn:
        conn.execute("UPDATE painter_profiles SET approved = ? WHERE telegram_id = ?", (1 if approved else 0, telegram_id))


def list_pending_painters():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM painter_profiles WHERE approved = 0").fetchall()
        return [dict(r) for r in rows]


def set_saas_tier(telegram_id, tier):
    """Upgrade or downgrade a painter's SaaS tier. tier: 'free', 'standard', 'premium'"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE painter_profiles SET saas_tier = ?, saas_since = ? WHERE telegram_id = ?",
            (tier, now(), telegram_id),
        )


def add_painter_points(telegram_id, points):
    with get_conn() as conn:
        conn.execute("UPDATE painter_profiles SET total_points = total_points + ? WHERE telegram_id = ?", (points, telegram_id))


# ─── Estimate functions ───────────────────────────────────────────────────────

def save_estimate(telegram_id, user_type, interior_area_m2, exterior_area_m2, brand_key,
                   interior_product, exterior_product, grand_total, estimate_dict,
                   wants_dealership_purchase=False):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO estimates
               (telegram_id, user_type, interior_area_m2, exterior_area_m2, brand_key,
                interior_product, exterior_product, grand_total, estimate_json,
                wants_dealership_purchase, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (telegram_id, user_type, interior_area_m2, exterior_area_m2, brand_key,
             interior_product, exterior_product, grand_total, json.dumps(estimate_dict),
             1 if wants_dealership_purchase else 0, now()),
        )
        return cur.lastrowid


def get_estimate(estimate_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM estimates WHERE estimate_id = ?", (estimate_id,)).fetchone()
        return dict(row) if row else None


# ─── Lead functions ────────────────────────────────────────────────────────────

def save_lead(telegram_id, estimate_id, customer_name, customer_phone, project_address, notes=None):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO leads
               (telegram_id, estimate_id, customer_name, customer_phone, project_address, notes, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'new', ?)""",
            (telegram_id, estimate_id, customer_name, customer_phone, project_address, notes, now()),
        )
        return cur.lastrowid


def list_leads(status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM leads WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def update_lead_status(lead_id, status):
    with get_conn() as conn:
        conn.execute("UPDATE leads SET status = ? WHERE lead_id = ?", (status, lead_id))


# ─── Purchase Order functions ─────────────────────────────────────────────────

def next_po_number():
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM purchase_orders").fetchone()["c"]
        return f"GTA-PO-{count + 1:06d}"


def create_purchase_order(telegram_id, estimate_id, brand_key, items_list, total_amount, fulfillment_method):
    po_number = next_po_number()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO purchase_orders
               (po_number, telegram_id, estimate_id, brand_key, items_json, total_amount,
                fulfillment_method, status, points_awarded, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)""",
            (po_number, telegram_id, estimate_id, brand_key, json.dumps(items_list),
             total_amount, fulfillment_method, now()),
        )
        return {"po_id": cur.lastrowid, "po_number": po_number}


def get_purchase_order(po_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
        return dict(row) if row else None


def list_purchase_orders(status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM purchase_orders WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM purchase_orders ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def confirm_purchase_order(po_id, admin_notes=None):
    """Admin marks a PO as confirmed (acknowledged, not yet fulfilled)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE purchase_orders SET status = 'confirmed', admin_notes = ? WHERE po_id = ?",
            (admin_notes, po_id),
        )


def fulfill_purchase_order(po_id, points_per_item=1, admin_notes=None):
    """
    Admin marks a PO as fulfilled. This is the trigger point that awards points.
    Points = total number of product UNITS in the PO (per Godtech's rule: points
    are earned per number of products purchased through the dealership, not per Naira).
    """
    with get_conn() as conn:
        po = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
        if not po:
            return None
        items = json.loads(po["items_json"])
        total_units = sum(item.get("qty", 0) for item in items)
        points_earned = total_units * points_per_item

        conn.execute(
            """UPDATE purchase_orders
               SET status = 'fulfilled', points_awarded = ?, admin_notes = ?, fulfilled_at = ?
               WHERE po_id = ?""",
            (points_earned, admin_notes, now(), po_id),
        )
        conn.execute(
            """INSERT INTO points_ledger (telegram_id, po_id, points_change, reason, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (po["telegram_id"], po_id, points_earned, f"Purchase Order {po['po_number']} fulfilled ({total_units} units)", now()),
        )
        conn.execute(
            "UPDATE painter_profiles SET total_points = total_points + ? WHERE telegram_id = ?",
            (points_earned, po["telegram_id"]),
        )
        return points_earned


def cancel_purchase_order(po_id, admin_notes=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE purchase_orders SET status = 'cancelled', admin_notes = ? WHERE po_id = ?",
            (admin_notes, po_id),
        )


def get_points_balance(telegram_id):
    with get_conn() as conn:
        row = conn.execute("SELECT total_points FROM painter_profiles WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return row["total_points"] if row else 0


def get_points_history(telegram_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM points_ledger WHERE telegram_id = ? ORDER BY created_at DESC",
            (telegram_id,),
        ).fetchall()
        return [dict(r) for r in rows]
