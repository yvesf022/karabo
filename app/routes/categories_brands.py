"""
app/routes/categories_brands.py
────────────────────────────────
GET /api/categories  — all 20 beauty subcategories with real product counts
GET /api/categories/{id}
GET /api/brands
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.models import Category, Brand

router = APIRouter(tags=["categories-brands"])

# Canonical order for the 20 subcategories
CATEGORY_ORDER = [
    "anti_aging", "acne", "brightening", "whitening", "hydration",
    "repair", "barrier", "eczema", "rosacea", "scar",
    "stretch_mark", "sunscreen", "oils", "soaps", "body",
    "masks", "exfoliation", "clinical_acids", "african_ingredients", "korean_ingredients",
]

CATEGORY_LABELS = {
    "anti_aging":          "Anti-Aging",
    "acne":                "Acne Care",
    "brightening":         "Brightening",
    "whitening":           "Whitening",
    "hydration":           "Hydration",
    "repair":              "Repair & Restore",
    "barrier":             "Skin Barrier",
    "eczema":              "Eczema Relief",
    "rosacea":             "Rosacea Care",
    "scar":                "Scar & Dark Spots",
    "stretch_mark":        "Stretch Marks",
    "sunscreen":           "Sunscreen",
    "oils":                "Facial & Body Oils",
    "soaps":               "Soaps & Cleansers",
    "body":                "Body Care",
    "masks":               "Masks & Treatments",
    "exfoliation":         "Exfoliation",
    "clinical_acids":      "Clinical Acids",
    "african_ingredients": "African Ingredients",
    "korean_ingredients":  "Korean Ingredients",
}


@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    """
    Returns all 20 beauty subcategories with real product counts.
    Only returns categories that have at least 1 active product.
    """
    rows = db.execute(text("""
        SELECT category, COUNT(*) as cnt
        FROM products
        WHERE status = 'active'
          AND is_deleted = FALSE
          AND category IS NOT NULL
          AND category != ''
        GROUP BY category
    """)).fetchall()
    counts: dict[str, int] = {r[0]: r[1] for r in rows}

    result = []
    for slug in CATEGORY_ORDER:
        count = counts.get(slug, 0)
        if count == 0:
            continue  # skip empty categories
        result.append({
            "id":            slug,
            "name":          CATEGORY_LABELS.get(slug, slug.replace("_", " ").title()),
            "slug":          slug,
            "image_url":     None,
            "parent_id":     None,
            "product_count": count,
        })

    # Also surface any category slugs in DB not in our list (safety net)
    known = set(CATEGORY_ORDER)
    for slug, count in counts.items():
        if slug and slug not in known and count > 0:
            result.append({
                "id":            slug,
                "name":          slug.replace("_", " ").title(),
                "slug":          slug,
                "image_url":     None,
                "parent_id":     None,
                "product_count": count,
            })

    return result


@router.get("/categories/{category_id}")
def get_category(category_id: str, db: Session = Depends(get_db)):
    slug = category_id
    name = CATEGORY_LABELS.get(slug, slug.replace("_", " ").title())
    row = db.execute(text("""
        SELECT COUNT(*) FROM products
        WHERE category = :slug AND status = 'active' AND is_deleted = FALSE
    """), {"slug": slug}).fetchone()
    count = row[0] if row else 0
    if count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    return {
        "id":            slug,
        "name":          name,
        "slug":          slug,
        "description":   None,
        "image_url":     None,
        "product_count": count,
    }


@router.get("/brands")
def get_brands(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT LOWER(brand) as brand_lower, brand, COUNT(*) as cnt
        FROM products
        WHERE status = 'active'
          AND is_deleted = FALSE
          AND brand IS NOT NULL
          AND brand != ''
        GROUP BY LOWER(brand), brand
        ORDER BY cnt DESC
    """)).fetchall()

    # Deduplicate by lowercase brand name (keep highest count version)
    seen = {}
    for r in rows:
        key = r[0]
        if key not in seen:
            seen[key] = {"name": r[1], "count": r[2]}

    return [
        {
            "id":            row["name"],
            "name":          row["name"],
            "slug":          row["name"].lower().replace(" ", "_"),
            "logo_url":      None,
            "product_count": row["count"],
        }
        for row in seen.values()
    ]