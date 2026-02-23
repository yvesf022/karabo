from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.models import Category, Brand

router = APIRouter(tags=["categories-brands"])


@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    """
    Returns all active categories with real product counts.
    The `slug` field is cross-checked against matched_category values
    in the products table so sidebar filtering always works.
    """
    categories = (
        db.query(Category)
        .filter(Category.is_active == True)
        .order_by(Category.position)
        .all()
    )

    # ✅ BUG FIX: `matched_category` is NOT a real database column — it is
    # only a CSV import header that maps onto the `category` column during
    # bulk upload.  Querying it caused a PostgreSQL "column does not exist"
    # error on every /api/categories request, which silently returned empty
    # counts and broke the store sidebar.  Use `category` instead.
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
    for c in categories:
        slug = c.slug or ""
        result.append({
            "id":            str(c.id),
            "name":          c.name,
            "slug":          slug,
            "image_url":     c.image_url,
            "parent_id":     str(c.parent_id) if c.parent_id else None,
            # ✅ FIX: product_count now looks up by `category` slug so counts
            # correctly match what the store filter actually returns.
            "product_count": counts.get(slug, 0),
        })

    # Also inject any `category` slugs that exist in products but have no
    # corresponding Category row — so the sidebar never silently hides
    # filterable categories that were imported via CSV bulk-upload.
    # ✅ BUG FIX: was using `matched_category` (not a DB column); fixed to `category`.
    known_slugs = {c["slug"] for c in result}
    for slug, count in counts.items():
        if slug and slug not in known_slugs:
            result.append({
                "id":            slug,          # use slug as id fallback
                "name":          slug.replace("_", " ").title(),
                "slug":          slug,
                "image_url":     None,
                "parent_id":     None,
                "product_count": count,
            })

    # Sort: categories with products first, then alphabetically
    result.sort(key=lambda c: (-c["product_count"], c["name"]))
    return result


@router.get("/categories/{category_id}")
def get_category(category_id: str, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    return {
        "id":          str(cat.id),
        "name":        cat.name,
        "slug":        cat.slug,
        "description": getattr(cat, "description", None),
        "image_url":   cat.image_url,
    }


@router.get("/brands")
def get_brands(db: Session = Depends(get_db)):
    brands = db.query(Brand).filter(Brand.is_active == True).all()

    # Add product counts per brand slug too
    rows = db.execute(text("""
        SELECT LOWER(brand), COUNT(*) as cnt
        FROM products
        WHERE status = 'active'
          AND is_deleted = FALSE
          AND brand IS NOT NULL
        GROUP BY LOWER(brand)
    """)).fetchall()
    brand_counts: dict[str, int] = {r[0]: r[1] for r in rows}

    return [
        {
            "id":            str(b.id),
            "name":          b.name,
            "slug":          b.slug,
            "logo_url":      b.logo_url,
            "product_count": brand_counts.get((b.slug or b.name or "").lower(), 0),
        }
        for b in brands
    ]