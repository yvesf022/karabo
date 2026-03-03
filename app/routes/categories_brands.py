"""
app/routes/categories_brands.py
────────────────────────────────
Dynamic Category & Brand Discovery
- Automatically detects categories from the products table.
- Groups uncategorized items into "Others".
- Only shows categories/brands with active, in-stock inventory.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db

router = APIRouter(tags=["categories-brands"])

@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    """
    Returns all categories currently used by active products.
    If a product has no category or is NULL, it's grouped under 'Others'.
    """
    # Normalize at query level: lowercase + replace spaces/dashes with underscores.
    # This collapses "Anti Aging", "anti-aging", "anti_aging" into the same slug,
    # so the filter URL always matches DB values regardless of how they were stored.
    query = text("""
        SELECT 
            COALESCE(
                NULLIF(TRIM(LOWER(REPLACE(REPLACE(category, ' ', '_'), '-', '_'))), ''),
                'others'
            ) AS cat_slug,
            COUNT(*) as product_count
        FROM products
        WHERE status = 'active' 
          AND is_deleted = FALSE 
          AND stock > 0
        GROUP BY cat_slug
        ORDER BY product_count DESC
    """)
    
    rows = db.execute(query).fetchall()
    
    categories = []
    for r in rows:
        # r[0] is now already a normalized slug (e.g. "anti_aging")
        # derived from the SQL normalization above.
        slug = r[0]
        name = slug.replace("_", " ").title()   # "anti_aging" → "Anti Aging"
        
        categories.append({
            "id":            slug,
            "name":          name,
            "slug":          slug,
            "product_count": r[1],
            "description":   f"Browse our selection of {name} products.",
            "image_url":     None,
        })
        
    return categories

@router.get("/categories/{slug}")
def get_category_detail(slug: str, db: Session = Depends(get_db)):
    """
    Returns details for a specific category.
    """
    # After backfill migration, DB values are clean slugs.
    # Query with the slug directly — no underscore→space replacement.
    if slug == "others":
        query = text("""
            SELECT COUNT(*) FROM products 
            WHERE (category IS NULL OR TRIM(category) = '' OR category = 'others')
              AND status = 'active' AND is_deleted = FALSE AND stock > 0
        """)
        row = db.execute(query).fetchone()
    else:
        # Match by exact slug OR case-insensitive for robustness during transition
        query = text("""
            SELECT COUNT(*) FROM products 
            WHERE LOWER(TRIM(category)) = LOWER(TRIM(:cat))
              AND status = 'active' AND is_deleted = FALSE AND stock > 0
        """)
        row = db.execute(query, {"cat": slug}).fetchone()
    count = row[0] if row else 0
    
    if count == 0:
        raise HTTPException(status_code=404, detail="Category contains no active products")

    return {
        "id": slug,
        "name": slug.replace("_", " ").title(),
        "slug": slug,
        "product_count": count
    }

@router.get("/brands")
def get_brands(db: Session = Depends(get_db)):
    """
    Returns all brands from active, in-stock products.
    """
    query = text("""
        SELECT 
            brand, 
            COUNT(*) as cnt
        FROM products
        WHERE status = 'active'
          AND is_deleted = FALSE
          AND stock > 0
          AND brand IS NOT NULL
          AND brand != ''
        GROUP BY brand
        ORDER BY cnt DESC
    """)
    
    rows = db.execute(query).fetchall()

    return [
        {
            "id": r[0].lower().replace(" ", "-"),
            "name": r[0],
            "slug": r[0].lower().replace(" ", "-"),
            "product_count": r[1]
        }
        for r in rows
    ]