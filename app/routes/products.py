from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from app.database import get_db
from app.models import Product, ProductStatus

router = APIRouter(prefix="/products", tags=["products"])


# =============================
# PUBLIC: LIST PRODUCTS
# (Filtering, Sorting, Pagination)
# =============================
@router.get("")
def list_products(
    db: Session = Depends(get_db),

    # Filters
    search_query: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock: Optional[bool] = None,
    min_rating: Optional[float] = None,

    # Sorting
    sort: Optional[str] = "featured",

    # Pagination
    page: int = 1,
    per_page: int = 20,
):
    # 🔒 Hard safety limits (Amazon-style)
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 20
    if per_page > 100:
        per_page = 100

    # Base query (only active products)
    query = db.query(Product).filter(Product.status == ProductStatus.active)

    # =============================
    # SEARCH (PostgreSQL full-text)
    # =============================
    if search_query:
        query = query.filter(
            func.to_tsvector("english", Product.title).match(search_query)
            | func.to_tsvector("english", Product.short_description).match(search_query)
        )

    # =============================
    # FILTERS
    # =============================
    if category:
        query = query.filter(Product.category == category)

    if brand:
        query = query.filter(Product.brand == brand)

    if min_price is not None:
        query = query.filter(Product.price >= min_price)

    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    if in_stock is not None:
        if in_stock:
            query = query.filter(Product.stock > 0)
        else:
            query = query.filter(Product.stock <= 0)

    if min_rating is not None:
        query = query.filter(Product.rating >= min_rating)

    # =============================
    # SORTING (Amazon-style)
    # =============================
    if sort == "price_low":
        query = query.order_by(Product.price.asc())
    elif sort == "price_high":
        query = query.order_by(Product.price.desc())
    elif sort == "rating":
        query = query.order_by(Product.rating.desc())
    elif sort == "new_arrivals":
        query = query.order_by(Product.created_at.desc())
    elif sort == "best_sellers":
        query = query.order_by(Product.sales.desc())
    else:
        # featured / default
        query = query.order_by(Product.created_at.desc())

    # =============================
    # PAGINATION
    # =============================
    offset = (page - 1) * per_page
    products = query.offset(offset).limit(per_page).all()

    # =============================
    # RESPONSE
    # =============================
    return [
        {
            "id": p.id,
            "title": p.title,
            "short_description": p.short_description,
            "price": p.price,
            "compare_price": p.compare_price,
            "brand": p.brand,
            "rating": p.rating,
            "sales": p.sales,
            "category": p.category,
            "in_stock": p.stock > 0,
            "main_image": p.main_image,
            "created_at": p.created_at,
        }
        for p in products
    ]
