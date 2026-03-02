"""
app/routes/categories_router.py
────────────────────────────────
GET /api/categories/departments  — department tree with real product images
GET /api/products/by-department/{dept}  — paginated products for a department

The only department is "beauty" since we only sell Beauty & Personal Care.
All 20 subcategory slugs match the products.category column exactly.
"""

from __future__ import annotations
import urllib.parse
from typing import Any
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.database import get_db

router = APIRouter()

# ── The 20 beauty subcategories (slug, display label) ──────────────────────
BEAUTY_SUBCATS = [
    ("anti_aging",          "Anti-Aging"),
    ("acne",                "Acne Care"),
    ("brightening",         "Brightening"),
    ("whitening",           "Whitening"),
    ("hydration",           "Hydration"),
    ("repair",              "Repair & Restore"),
    ("barrier",             "Skin Barrier"),
    ("eczema",              "Eczema Relief"),
    ("rosacea",             "Rosacea Care"),
    ("scar",                "Scar & Dark Spots"),
    ("stretch_mark",        "Stretch Marks"),
    ("sunscreen",           "Sunscreen"),
    ("oils",                "Facial & Body Oils"),
    ("soaps",               "Soaps & Cleansers"),
    ("body",                "Body Care"),
    ("masks",               "Masks & Treatments"),
    ("exfoliation",         "Exfoliation"),
    ("clinical_acids",      "Clinical Acids"),
    ("african_ingredients", "African Ingredients"),
    ("korean_ingredients",  "Korean Ingredients"),
]

BEAUTY_SLUGS = [s[0] for s in BEAUTY_SUBCATS]


def _href(field: str, value: str) -> str:
    return f"/store?{field}={urllib.parse.quote(value)}"


@router.get("/categories/departments")
def get_departments() -> JSONResponse:
    """
    Returns the single Beauty & Personal Care department with all
    20 subcategories, each with a real product image from the DB.
    Only subcategories that have at least 1 active product are included.
    """
    db = next(get_db())
    try:
        beauty_subs = []
        for slug, label in BEAUTY_SUBCATS:
            row = db.execute(text("""
                SELECT COALESCE(main_image, image_url) AS img
                FROM products
                WHERE category = :slug
                  AND is_deleted = FALSE
                  AND status = 'active'
                  AND COALESCE(main_image, image_url) IS NOT NULL
                ORDER BY rating DESC NULLS LAST
                LIMIT 1
            """), {"slug": slug}).fetchone()

            if row:  # only include subcats that have products
                beauty_subs.append({
                    "key":   slug,
                    "label": label,
                    "href":  _href("category", slug),
                    "image": row[0],
                })

        beauty_img = beauty_subs[0]["image"] if beauty_subs else None

        result = [{
            "key":           "beauty",
            "title":         "Beauty & Personal Care",
            "href":          "/store?dept=beauty",
            "image":         beauty_img,
            "subcategories": beauty_subs,
        }]

        return JSONResponse(content=result)
    finally:
        db.close()


_SORT_MAP = {
    "newest":     ("created_at", "DESC"),
    "price_asc":  ("price",      "ASC"),
    "price_desc": ("price",      "DESC"),
    "rating":     ("rating",     "DESC"),
    "sales":      ("sales",      "DESC"),
    "popular":    ("sales",      "DESC"),
    "discount":   ("compare_price", "DESC"),
}
_ALLOWED_SORT = {"rating", "price", "sales", "created_at", "compare_price"}


@router.get("/products/by-department/{dept}")
def products_by_department(
    dept: str,
    page: int = 1,
    per_page: int = 40,
    sort_by: str = "rating",
    sort_order: str = "desc",
    sort: str = "",
) -> JSONResponse:
    """
    GET /api/products/by-department/beauty?page=1&per_page=40
    Returns all products across all 20 beauty subcategories.
    """
    if dept != "beauty":
        return JSONResponse(content={"results": [], "total": 0, "page": page, "per_page": per_page})

    slugs = BEAUTY_SLUGS
    db = next(get_db())
    try:
        placeholders = ", ".join(f":slug_{i}" for i in range(len(slugs)))
        bind = {f"slug_{i}": s for i, s in enumerate(slugs)}

        if sort in _SORT_MAP:
            col, direction = _SORT_MAP[sort]
        else:
            col       = sort_by if sort_by in _ALLOWED_SORT else "rating"
            direction = "DESC" if sort_order.lower() == "desc" else "ASC"

        count_row = db.execute(text(f"""
            SELECT COUNT(*) FROM products
            WHERE category IN ({placeholders})
              AND is_deleted = FALSE
              AND status = 'active'
        """), bind).fetchone()
        total = count_row[0] if count_row else 0

        offset = (page - 1) * per_page
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
            price, compare_price = r[2], r[3]
            discount_pct = (
                round(((compare_price - price) / compare_price) * 100)
                if compare_price and compare_price > price > 0 else None
            )
            results.append({
                "id":            str(r[0]),
                "title":         r[1],
                "price":         price,
                "compare_price": compare_price,
                "discount_pct":  discount_pct,
                "brand":         r[4],
                "category":      r[5],
                "main_image":    r[6],
                "image_url":     r[6],
                "rating":        r[7],
                "rating_number": r[8],
                "in_stock":      r[9],
                "sales":         r[10],
            })

        return JSONResponse(content={
            "results": results, "total": total, "page": page, "per_page": per_page
        })
    finally:
        db.close()