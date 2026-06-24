"""
price_database_loader.py
Thin helper so bot.py doesn't need to load the full DB just to get a display name.
"""
import json
import os

_DB = None


def _load():
    global _DB
    if _DB is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "price_database.json")
        with open(path, "r", encoding="utf-8") as f:
            _DB = json.load(f)
    return _DB


def get_brand_display_name(brand_key: str) -> str:
    db = _load()
    brand = db["brands"].get(brand_key, {})
    return brand.get("display_name", brand_key)


def list_brands():
    db = _load()
    return [
        {"key": k, "display_name": v["display_name"], "is_default": v.get("is_dealership_default", False)}
        for k, v in db["brands"].items()
    ]
