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

router = APIRouter(prefix="/api", tags=["categories-brands"])

@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    """
    Returns all categories currently used by active products.
    If a product has no category or is NULL, it's grouped under 'Others'.
    """
    # This query pulls all unique categories from your 1,000 products.
    # COALESCE(category, 'others') ensures that if 'category' is empty, it becomes 'others'.
    query = text("""
        SELECT 
            COALESCE(NULLIF(TRIM(category), ''), 'others') as cat_name,
            COUNT(*) as product_count
        FROM products
        WHERE status = 'active' 
          AND is_deleted = FALSE 
          AND stock > 0
        GROUP BY cat_name
        ORDER BY product_count DESC
    """)
    
    rows = db.execute(query).fetchall()
    
    categories = []
    for r in rows:
        slug = r[0].lower().replace(" ", "_")
        name = r[0].title()
        
        categories.append({
            "id": slug,
            "name": name,
            "slug": slug,
            "product_count": r[1],
            "description": f"Browse our selection of {name} products.",
            "image_url": None  # Can be mapped to a static asset if needed
        })
        
    return categories

@router.get("/categories/{slug}")
def get_category_detail(slug: str, db: Session = Depends(get_db)):
    """
    Returns details for a specific category.
    """
    # Handle the 'others' case specifically
    cat_filter = slug.replace("_", " ")
    
    if slug == "others":
        query = text("""
            SELECT COUNT(*) FROM products 
            WHERE (category IS NULL OR category = '' OR category = 'others')
              AND status = 'active' AND is_deleted = FALSE AND stock > 0
        """)
    else:
        query = text("""
            SELECT COUNT(*) FROM products 
            WHERE LOWER(category) = LOWER(:cat)
              AND status = 'active' AND is_deleted = FALSE AND stock > 0
        """)

    row = db.execute(query, {"cat": cat_filter}).fetchone()
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