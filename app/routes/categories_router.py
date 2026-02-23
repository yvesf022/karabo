"""
app/routers/categories.py
─────────────────────────
Provides GET /api/categories — returns the two main product departments
(Beauty & Personal Care, Cell Phones & Accessories) with subcategories and
representative product images drawn from the actual products in the DB.

Include in main.py:
    from app.routers import categories as categories_router
    app.include_router(categories_router.router, prefix="/api")

Endpoint:  GET /api/categories
Response:
    [
      {
        "key": "beauty",
        "title": "Beauty & Personal Care",
        "href": "/store?main_category=Beauty+%26+Personal+Care",
        "image": "https://...",          # from a real product
        "subcategories": [
          {"key": "sunscreen", "label": "Sunscreen", "href": "...", "image": "..."},
          ...
        ]
      },
      { "key": "phones", ... }
    ]
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import get_db

router = APIRouter()

# ──────────────────────────────────────────────
# Static category metadata (label, slug, URL)
# ──────────────────────────────────────────────
BEAUTY_SUBCATS = [
    ("moisturizer",      "Moisturisers"),
    ("sunscreen",        "Sunscreen"),
    ("face_wash",        "Face Wash"),
    ("serum",            "Serums"),
    ("body_lotion",      "Body Lotion"),
    ("face_mask",        "Face Masks"),
    ("eye_mask",         "Eye Masks"),
    ("anti_acne",        "Anti-Acne"),
    ("skin_brightening", "Skin Brightening"),
    ("collagen",         "Collagen Care"),
    ("skin_natural_oils","Natural Oils"),
    ("herbal_oils",      "Herbal Oils"),
    ("anti_wrinkles",    "Anti-Wrinkle"),
    ("body_wash",        "Body Wash"),
    ("exfoliator",       "Exfoliators"),
    ("lip_mask",         "Lip Masks"),
]

PHONE_SUBCATS = [
    ("samsung",  "Samsung"),
    ("apple",    "Apple"),
    ("xiaomi",   "Xiaomi"),
    ("motorola", "Motorola"),
    ("oneplus",  "OnePlus"),
    ("google",   "Google Pixel"),
    ("realme",   "Realme"),
]


def _make_href(field: str, value: str) -> str:
    import urllib.parse
    return f"/store?{field}={urllib.parse.quote(value)}"


@router.get("/categories/departments")
def get_categories() -> JSONResponse:
    """
    Returns the full department tree with real product images fetched from DB.
    Falls back to None image if no matching product is found.
    """
    db = next(get_db())
    try:
        result: list[dict[str, Any]] = []

        # ── BEAUTY ─────────────────────────────────────────────
        beauty_subs = []
        for key, label in BEAUTY_SUBCATS:
            row = db.execute(text("""
                SELECT COALESCE(main_image, image_url) as img
                FROM products
                WHERE matched_category = :key
                  AND is_deleted = FALSE
                  AND COALESCE(main_image, image_url) IS NOT NULL
                ORDER BY rating DESC NULLS LAST
                LIMIT 1
            """), {"key": key}).fetchone()

            beauty_subs.append({
                "key":   key,
                "label": label,
                "href":  _make_href("category", key),
                "image": row[0] if row else None,
            })

        # Top image for the section: first sub with an image
        beauty_img = next(
            (s["image"] for s in beauty_subs if s["image"]), None
        )

        result.append({
            "key":           "beauty",
            "title":         "Beauty & Personal Care",
            "href":          _make_href("main_category", "Beauty & Personal Care"),
            "image":         beauty_img,
            "subcategories": beauty_subs,
        })

        # ── PHONES ─────────────────────────────────────────────
        phone_subs = []
        for key, label in PHONE_SUBCATS:
            row = db.execute(text("""
                SELECT COALESCE(main_image, image_url) as img
                FROM products
                WHERE matched_category = :key
                  AND is_deleted = FALSE
                  AND COALESCE(main_image, image_url) IS NOT NULL
                ORDER BY rating DESC NULLS LAST
                LIMIT 1
            """), {"key": key}).fetchone()

            phone_subs.append({
                "key":   key,
                "label": label,
                "href":  _make_href("category", key),
                "image": row[0] if row else None,
            })

        phones_img = next(
            (s["image"] for s in phone_subs if s["image"]), None
        )

        result.append({
            "key":           "phones",
            "title":         "Cell Phones & Accessories",
            "href":          _make_href("main_category", "Cell Phones & Accessories"),
            "image":         phones_img,
            "subcategories": phone_subs,
        })

        return JSONResponse(content=result)

    finally:
        db.close()