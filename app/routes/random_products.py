# app/routes/random_products.py
"""
Random Products API
====================
Serves genuinely random products from across the entire catalogue,
perfect for homepage hero grids, "You May Also Like" widgets, and
store discovery carousels.

Two endpoints:
  GET /api/products/random
      ?count=20          number of products to return (default 20, max 100)
      ?with_images=true  only return products that have at least one image (default true)
      ?seed=<int>        optional integer seed for reproducible randomness
                         (useful for SSR/hydration consistency)
      ?exclude=id1,id2   comma-separated product IDs to exclude

  GET /api/products/random/categories
      Returns one random product per distinct category — ideal for a
      "browse all departments" grid.

Algorithm (PostgreSQL):
  ORDER BY RANDOM() is a true table scan shuffle — perfect for small-to-
  medium catalogues (< 500 k rows).  For very large tables you could swap
  to the TABLESAMPLE BERNOULLI approach, but RANDOM() is simpler and
  correct for our use-case.

  When a seed is supplied we use setseed() + RANDOM() so the same seed
  always returns the same order — useful when the server-side render and
  the client hydration need identical data.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func, text
from typing import Optional

from app.database import get_db
from app.models import Product

router = APIRouter(prefix="/products", tags=["products"])


# ─────────────────────────────────────────────────────────────────
# SHARED SERIALISER  (same shape as list_products results)
# ─────────────────────────────────────────────────────────────────

def _card(p: Product) -> dict:
    img = (
        next((i.image_url for i in p.images if i.is_primary), None)
        or (p.images[0].image_url if p.images else None)
    )
    disc = None
    if p.compare_price and p.compare_price > p.price > 0:
        disc = round(((p.compare_price - p.price) / p.compare_price) * 100)
    return {
        "id":                str(p.id),
        "title":             p.title,
        "short_description": p.short_description,
        "price":             p.price,
        "compare_price":     p.compare_price,
        "discount_pct":      disc,
        "brand":             p.brand,
        "store":             p.store,
        "store_id":          str(p.store_id) if p.store_id else None,
        "rating":            p.rating,
        "rating_number":     p.rating_number,
        "sales":             p.sales,
        "category":          p.category,
        "main_category":     p.main_category,
        "stock":             p.stock,
        "in_stock":          p.stock > 0,
        "main_image":        img,
        "images":            [i.image_url for i in p.images],
        "created_at":        p.created_at,
    }


# ─────────────────────────────────────────────────────────────────
# BASE QUERY — active, not-deleted, in-stock products with images
# ─────────────────────────────────────────────────────────────────

def _base(db: Session, with_images: bool = True, exclude_ids: list[str] | None = None):
    q = db.query(Product).options(selectinload(Product.images)).filter(
        Product.status     == "active",
        Product.is_deleted == False,
        Product.stock      > 0,
    )
    # Note: we removed the images.any() filter — products may have images stored
    # differently and filtering here was causing empty results for new stores.
    if exclude_ids:
        q = q.filter(Product.id.notin_(exclude_ids))
    return q


# ─────────────────────────────────────────────────────────────────
# GET /api/products/random
# ─────────────────────────────────────────────────────────────────

@router.get("/random")
def random_products(
    db:          Session       = Depends(get_db),
    count:       int           = Query(20,   ge=1,  le=100),
    with_images: bool          = Query(True),
    seed:        Optional[int] = Query(None),
    exclude:     Optional[str] = Query(None,  description="Comma-separated product IDs to exclude"),
    diverse:     bool          = Query(False, description="If true, ensure category diversity (one per category then fill)"),
):
    """
    Return `count` genuinely random active products.

    - Uses PostgreSQL ORDER BY RANDOM() for a true catalogue-wide shuffle.
    - If `seed` is provided, calls setseed() first so results are
      reproducible for that seed value (handy for SSR).
    - Products without images are excluded by default (`with_images=true`).
    - If `diverse=true`, picks up to one product per category first, then
      fills remaining slots randomly — guarantees visual variety in hero grids.
    """
    exclude_ids = [x.strip() for x in exclude.split(",")] if exclude else []

    # Apply seed for reproducible randomness when needed
    if seed is not None:
        normalised = ((seed % 10000) / 10000.0) * 2 - 1
        db.execute(text(f"SELECT setseed({normalised:.6f})"))

    if diverse:
        # ── Diverse mode: one product per category, then fill the rest ──
        # Get distinct categories that have qualifying products
        cats_q = (
            _base(db, with_images=with_images, exclude_ids=exclude_ids)
            .with_entities(Product.category)
            .filter(Product.category != None)
            .distinct()
            .order_by(func.random())
            .limit(count)
            .all()
        )
        categories = [r[0] for r in cats_q if r[0]]

        seen_ids: set = set()
        result: list[Product] = []

        # One random product per category
        for cat in categories:
            if len(result) >= count:
                break
            p = (
                _base(db, with_images=with_images, exclude_ids=exclude_ids)
                .filter(Product.category == cat)
                .order_by(func.random())
                .first()
            )
            if p and p.id not in seen_ids:
                result.append(p)
                seen_ids.add(p.id)

        # Fill remaining slots with any random products not already chosen
        if len(result) < count:
            extra_exclude = exclude_ids + [str(p.id) for p in result]
            extras = (
                _base(db, with_images=with_images, exclude_ids=extra_exclude)
                .order_by(func.random())
                .limit(count - len(result))
                .all()
            )
            result.extend(extras)

        return {
            "count":    len(result),
            "products": [_card(p) for p in result],
        }

    products = (
        _base(db, with_images=with_images, exclude_ids=exclude_ids)
        .order_by(func.random())
        .limit(count)
        .all()
    )

    return {
        "count":    len(products),
        "products": [_card(p) for p in products],
    }


# ─────────────────────────────────────────────────────────────────
# GET /api/products/random/categories
# ─────────────────────────────────────────────────────────────────

@router.get("/random/categories")
def random_by_category(
    db:          Session = Depends(get_db),
    per_category: int    = Query(6, ge=1, le=20),
    max_cats:    int     = Query(12, ge=1, le=30),
    with_images: bool    = Query(True),
):
    """
    Return up to `per_category` random products for each of the top
    `max_cats` distinct categories.  The categories themselves are
    chosen randomly so the homepage always feels fresh.

    Response shape:
      {
        "categories": [
          { "category": "Smartphones", "products": [...] },
          ...
        ]
      }
    """
    # Get all distinct non-null categories that have in-stock products
    cats_query = (
        db.query(Product.category)
        .filter(
            Product.status     == "active",
            Product.is_deleted == False,
            Product.stock      > 0,
            Product.category   != None,
        )
        .distinct()
        .order_by(func.random())
        .limit(max_cats)
        .all()
    )
    categories = [row[0] for row in cats_query if row[0]]

    result = []
    for cat in categories:
        prods = (
            _base(db, with_images=with_images)
            .filter(Product.category == cat)
            .order_by(func.random())
            .limit(per_category)
            .all()
        )
        if prods:
            result.append({
                "category": cat,
                "products": [_card(p) for p in prods],
            })

    return {"categories": result}