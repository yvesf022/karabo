from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Product, ProductStatus
from typing import Optional

router = APIRouter(prefix="/products", tags=["products"])

# =============================
# PUBLIC: LIST PRODUCTS WITH FILTERING, SORTING, AND PAGINATION
# =============================
@router.get("")
def list_products(
    db: Session = Depends(get_db),
    search_query: Optional[str] = None,  # New search query parameter
    category: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    in_stock: Optional[bool] = None,
    brand: Optional[str] = None,
    ratings: Optional[int] = None,
    sort: Optional[str] = "featured",
    page: Optional[int] = 1,
    per_page: Optional[int] = 20,
):
    # Build the query
    query = db.query(Product).filter(Product.status == ProductStatus.active)

    # Apply filters
    if search_query:
        query = query.filter(
            func.to_tsvector(Product.title).match(search_query) |
            func.to_tsvector(Product.short_description).match(search_query)
        )
    if category:
        query = query.filter(Product.category == category)
    if min_price:
        query = query.filter(Product.price >= min_price)
    if max_price:
        query = query.filter(Product.price <= max_price)
    if in_stock is not None:
        query = query.filter(Product.in_stock == in_stock)
    if brand:
        query = query.filter(Product.brand == brand)  # New filter by brand
    if ratings:
        query = query.filter(Product.rating >= ratings)  # New filter by minimum rating

    # Sorting logic
    if sort == "price_low":
        query = query.order_by(Product.price)
    elif sort == "price_high":
        query = query.order_by(Product.price.desc())
    elif sort == "rating":
        query = query.order_by(Product.rating.desc())
    elif sort == "new_arrivals":
        query = query.order_by(Product.created_at.desc())  # New sorting by newest products
    elif sort == "best_sellers":
        query = query.order_by(Product.sales.desc())  # Sort by best-selling products

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
            "brand": p.brand,  # Return brand information
            "in_stock": p.in_stock,
        }
        for p in products
    ]
