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
    img = (getattr(p, 'main_image', None) or getattr(p, 'image_url', None)
           or next((i.image_url for i in p.images if i.is_primary), None)
           or (p.images[0].image_url if p.images else None))
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
        # ── Diverse mode: one random product per category in a SINGLE query ──
        # Old approach: one DB round-trip per category (40+ sequential queries).
        # New approach: DISTINCT ON (category) with RANDOM() — one query total.
        exclude_clause = ""
        bind: dict = {"lim": count}
        if exclude_ids:
            placeholders = ",".join(f":ex_{i}" for i in range(len(exclude_ids)))
            exclude_clause = f"AND id NOT IN ({placeholders})"
            for i, eid in enumerate(exclude_ids):
                bind[f"ex_{i}"] = eid

        img_clause = "AND COALESCE(main_image, image_url) IS NOT NULL" if with_images else ""

        # Apply seed
        if seed is not None:
            normalised = ((seed % 10000) / 10000.0) * 2 - 1
            db.execute(text(f"SELECT setseed({normalised:.6f})"))

        # One random product per category, then fill remaining slots
        diverse_rows = db.execute(text(f"""
            WITH ranked AS (
                SELECT id, title, price, compare_price, brand, category,
                       main_category, short_description, stock, sales,
                       rating, rating_number,
                       COALESCE(main_image, image_url) AS main_image,
                       created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY category
                           ORDER BY RANDOM()
                       ) AS rn
                FROM products
                WHERE status = 'active'
                  AND is_deleted = FALSE
                  AND stock > 0
                  AND category IS NOT NULL
                  {img_clause}
                  {exclude_clause}
            )
            SELECT id, title, price, compare_price, brand, category,
                   main_category, short_description, stock, sales,
                   rating, rating_number, main_image, created_at
            FROM ranked
            WHERE rn = 1
            ORDER BY RANDOM()
            LIMIT :lim
        """), bind).fetchall()

        def _row_card(r) -> dict:
            price, compare = r[2], r[3]
            disc = round(((compare - price) / compare) * 100) if compare and compare > price > 0 else None
            return {
                "id": str(r[0]), "title": r[1],
                "price": price, "compare_price": compare, "discount_pct": disc,
                "brand": r[4], "category": r[5], "main_category": r[6],
                "short_description": r[7], "stock": r[8], "sales": r[9],
                "rating": r[10], "rating_number": r[11],
                "in_stock": (r[8] or 0) > 0,
                "main_image": r[12], "images": [],
                "created_at": str(r[13]) if r[13] else None,
            }

        products_out = [_row_card(r) for r in diverse_rows]

        # If we got fewer than count (fewer categories than requested), fill with randoms
        if len(products_out) < count:
            seen = {r[0] for r in diverse_rows}
            seen_str = ", ".join(f":seen_{i}" for i in range(len(seen)))
            extra_bind: dict = {"lim2": count - len(products_out)}
            extra_where = ""
            if seen:
                extra_where = f"AND id NOT IN ({seen_str})"
                for i, sid in enumerate(seen):
                    extra_bind[f"seen_{i}"] = sid
            extra_rows = db.execute(text(f"""
                SELECT id, title, price, compare_price, brand, category,
                       main_category, short_description, stock, sales,
                       rating, rating_number,
                       COALESCE(main_image, image_url) AS main_image,
                       created_at
                FROM products
                WHERE status = 'active' AND is_deleted = FALSE AND stock > 0
                  {img_clause} {extra_where}
                ORDER BY RANDOM()
                LIMIT :lim2
            """), extra_bind).fetchall()
            products_out.extend(_row_card(r) for r in extra_rows)

        return {"count": len(products_out), "products": products_out}

    # ── Non-diverse: simple random sample ────────────────────────────────────
    img_clause = "AND COALESCE(main_image, image_url) IS NOT NULL" if with_images else ""
    exc_clause = ""
    bind2: dict = {"lim": count}
    if exclude_ids:
        ph = ",".join(f":ex_{i}" for i in range(len(exclude_ids)))
        exc_clause = f"AND id NOT IN ({ph})"
        for i, eid in enumerate(exclude_ids):
            bind2[f"ex_{i}"] = eid

    simple_rows = db.execute(text(f"""
        SELECT id, title, price, compare_price, brand, category,
               main_category, short_description, stock, sales,
               rating, rating_number,
               COALESCE(main_image, image_url) AS main_image,
               created_at
        FROM products
        WHERE status = 'active'
          AND is_deleted = FALSE
          AND stock > 0
          {img_clause}
          {exc_clause}
        ORDER BY RANDOM()
        LIMIT :lim
    """), bind2).fetchall()

    def _row_card2(r) -> dict:
        price, compare = r[2], r[3]
        disc = round(((compare - price) / compare) * 100) if compare and compare > price > 0 else None
        return {
            "id": str(r[0]), "title": r[1],
            "price": price, "compare_price": compare, "discount_pct": disc,
            "brand": r[4], "category": r[5], "main_category": r[6],
            "short_description": r[7], "stock": r[8], "sales": r[9],
            "rating": r[10], "rating_number": r[11],
            "in_stock": (r[8] or 0) > 0,
            "main_image": r[12], "images": [],
            "created_at": str(r[13]) if r[13] else None,
        }

    return {"count": len(simple_rows), "products": [_row_card2(r) for r in simple_rows]}


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