from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.database import get_db
from app.models import Product, Category, Brand

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search_products(
    q: str = Query(..., min_length=1),
    category: str = None,
    brand: str = None,
    min_price: float = None,
    max_price: float = None,
    in_stock: bool = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Search products."""
    query = db.query(Product).filter(Product.status == "active")

    # Text search
    search_term = f"%{q}%"
    query = query.filter(
        or_(
            Product.title.ilike(search_term),
            Product.short_description.ilike(search_term),
            Product.description.ilike(search_term),
            Product.brand.ilike(search_term),
            Product.category.ilike(search_term),
        )
    )

    # Filters
    if category:
        query = query.filter(Product.category == category)
    if brand:
        query = query.filter(Product.brand == brand)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    if in_stock is not None:
        query = query.filter(Product.in_stock == in_stock)

    # Pagination
    total = query.count()
    products = query.offset((page - 1) * limit).limit(limit).all()

    return {
        "results": [
            {
                "id": str(p.id),
                "title": p.title,
                "price": p.price,
                "brand": p.brand,
                "category": p.category,
                "rating": p.rating,
                "in_stock": p.in_stock,
            }
            for p in products
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/suggestions")
def search_suggestions(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Get search suggestions."""
    search_term = f"%{q}%"
    
    products = (
        db.query(Product.title)
        .filter(Product.status == "active", Product.title.ilike(search_term))
        .limit(limit)
        .all()
    )

    return {"suggestions": [p.title for p in products]}
