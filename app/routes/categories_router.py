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
        "href": "/store?main_cat=beauty",
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
                WHERE category = :key
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
            "href":          "/store?main_cat=beauty",
            "image":         beauty_img,
            "subcategories": beauty_subs,
        })

        # ── PHONES ─────────────────────────────────────────────
        phone_subs = []
        for key, label in PHONE_SUBCATS:
            row = db.execute(text("""
                SELECT COALESCE(main_image, image_url) as img
                FROM products
                WHERE category = :key
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
            "href":          "/store?main_cat=phones",
            "image":         phones_img,
            "subcategories": phone_subs,
        })

        return JSONResponse(content=result)

    finally:
        db.close()


# ── Beauty & Personal Care — all products ──────────────────────────────
BEAUTY_SLUGS = [
    "moisturizer","sunscreen","face_wash","serum","body_lotion","face_mask",
    "eye_mask","anti_acne","skin_brightening","collagen","skin_natural_oils",
    "herbal_oils","anti_wrinkles","body_wash","exfoliator","lip_mask",
]
PHONE_SLUGS = ["samsung","apple","xiaomi","motorola","oneplus","google","realme"]


@router.get("/products/by-department/{dept}")
def products_by_department(
    dept: str,
    page: int = 1,
    per_page: int = 40,
    sort_by: str = "rating",
    sort_order: str = "desc",
    # ✅ FIX Bug 3: StoreClient sends a single combined `sort` param
    # (e.g. "newest", "price_asc", "rating") — accept it so sorting works.
    sort: str = "",
) -> JSONResponse:
    """
    GET /api/products/by-department/beauty?page=1&per_page=40
    GET /api/products/by-department/phones?page=1&per_page=40

    Returns products belonging to a department (all beauty or all phone subcategories).
    Used by the StoreClient when user clicks "View All Beauty / Phones".
    """
    if dept == "beauty":
        slugs = BEAUTY_SLUGS
    elif dept == "phones":
        slugs = PHONE_SLUGS
    else:
        return JSONResponse(content={"results": [], "total": 0, "page": page, "per_page": per_page})

    db = next(get_db())
    try:
        placeholders = ", ".join(f":slug_{i}" for i in range(len(slugs)))
        bind = {f"slug_{i}": s for i, s in enumerate(slugs)}

        # ── Sort resolution ────────────────────────────────────────────────
        # The frontend sends a single combined `sort` value (e.g. "newest",
        # "price_asc", "rating") via the `sort` query param. The endpoint
        # also accepts the older `sort_by` + `sort_order` pair for backwards
        # compatibility. Resolve whichever is present.
        _SORT_MAP = {
            "newest":     ("created_at", "DESC"),
            "price_asc":  ("price",      "ASC"),
            "price_desc": ("price",      "DESC"),
            "rating":     ("rating",     "DESC"),
            "sales":      ("sales",      "DESC"),
            "popular":    ("sales",      "DESC"),
            "discount":   ("compare_price", "DESC"),  # proxy; real discount computed in Python
        }
        allowed_sort = {"rating", "price", "sales", "created_at", "compare_price"}

        if sort in _SORT_MAP:
            col, direction = _SORT_MAP[sort]
        else:
            # Fall back to explicit sort_by / sort_order params
            col       = sort_by if sort_by in allowed_sort else "rating"
            direction = "DESC" if sort_order.lower() == "desc" else "ASC"

        count_row = db.execute(text(f"""
            SELECT COUNT(*) FROM products
            WHERE category IN ({placeholders})
              AND is_deleted = FALSE
              AND status = 'active'
        """), bind).fetchone()
        total = count_row[0] if count_row else 0

        offset = (page - 1) * per_page
        # ✅ BUG FIX: removed `discount_pct` from SELECT — it is NOT a real
        # database column (it is always computed in Python from price/compare_price).
        # Selecting it was causing a PostgreSQL "column does not exist" error
        # which silently returned 0 results on the department pages.
        rows = db.execute(text(f"""
            SELECT id, title, price, compare_price, brand,
                   category,
                   COALESCE(main_image, image_url) as main_image,
                   rating, rating_number, in_stock, sales
            FROM products
            WHERE category IN ({placeholders})
              AND is_deleted = FALSE
              AND status = 'active'
            ORDER BY {col} {direction} NULLS LAST
            LIMIT :limit OFFSET :offset
        """), {**bind, "limit": per_page, "offset": offset}).fetchall()

        results = []
        for r in rows:
            price         = r[2]
            compare_price = r[3]
            # Compute discount_pct in Python — consistent with the main products endpoint
            discount_pct = (
                round(((compare_price - price) / compare_price) * 100)
                if compare_price and compare_price > price > 0
                else None
            )
            results.append({
                "id":            str(r[0]),
                "title":         r[1],
                "price":         price,
                "compare_price": compare_price,
                "discount_pct":  discount_pct,   # ✅ computed, not from DB column
                "brand":         r[4],
                "category":      r[5],
                "main_image":    r[6],
                "image_url":     r[6],
                "rating":        r[7],
                "rating_number": r[8],
                "in_stock":      r[9],
                "sales":         r[10],
            })

        return JSONResponse(content={"results": results, "total": total, "page": page, "per_page": per_page})

    finally:
        db.close()