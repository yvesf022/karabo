from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models import Product, ProductStatus
from app.dependencies import require_admin
from typing import Optional

router = APIRouter(prefix="/products", tags=["products"])

# =============================
# PUBLIC: LIST PRODUCTS WITH FILTERING, SORTING, AND PAGINATION
# =============================
@router.get("")
def list_products(
    db: Session = Depends(get_db),
    category: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    in_stock: Optional[bool] = None,
    sort: Optional[str] = "featured",
    page: Optional[int] = 1,
    per_page: Optional[int] = 20,
):
    # Build the query
    query = db.query(Product).filter(Product.status == ProductStatus.active)

    # Apply filters
    if category:
        query = query.filter(Product.category == category)
    if min_price:
        query = query.filter(Product.price >= min_price)
    if max_price:
        query = query.filter(Product.price <= max_price)
    if in_stock is not None:
        query = query.filter(Product.in_stock == in_stock)

    # Sorting logic
    if sort == "price_low":
        query = query.order_by(Product.price)
    elif sort == "price_high":
        query = query.order_by(Product.price.desc())
    elif sort == "rating":
        query = query.order_by(Product.rating.desc())
    # Add more sorting options as needed

    # Pagination logic
    skip = (page - 1) * per_page
    products = query.offset(skip).limit(per_page).all()

    return [
        {
            "id": p.id,
            "title": p.title,
            "short_description": p.short_description,
            "price": p.price,
            "compare_price": p.compare_price,
            "main_image": p.main_image,
            "category": p.category,
            "in_stock": p.in_stock,
        }
        for p in products
    ]
