from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
)
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
import uuid
import os

from app.database import get_db
from app.models import Product
from app.dependencies import require_admin

router = APIRouter(prefix="/products", tags=["products"])

UPLOAD_DIR = "uploads/products"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =====================================================
# PUBLIC: LIST PRODUCTS
# =====================================================
@router.get("")
def list_products(
    db: Session = Depends(get_db),

    search_query: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock: Optional[bool] = None,
    min_rating: Optional[float] = None,

    sort: Optional[str] = "featured",

    page: int = 1,
    per_page: int = 20,
):
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 20
    if per_page > 100:
        per_page = 100

    query = db.query(Product).filter(Product.status == "active")

    if search_query:
        query = query.filter(
            func.to_tsvector("english", Product.title).match(search_query)
            | func.to_tsvector(
                "english", Product.short_description
            ).match(search_query)
        )

    if category:
        query = query.filter(Product.category == category)

    if brand:
        query = query.filter(Product.brand == brand)

    if min_price is not None:
        query = query.filter(Product.price >= min_price)

    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    if in_stock is not None:
        query = query.filter(Product.stock > 0 if in_stock else Product.stock <= 0)

    if min_rating is not None:
        query = query.filter(Product.rating >= min_rating)

    if sort == "price_low":
        query = query.order_by(Product.price.asc())
    elif sort == "price_high":
        query = query.order_by(Product.price.desc())
    elif sort == "rating":
        query = query.order_by(Product.rating.desc())
    elif sort == "best_sellers":
        query = query.order_by(Product.sales.desc())
    else:
        query = query.order_by(Product.created_at.desc())

    offset = (page - 1) * per_page
    products = query.offset(offset).limit(per_page).all()

    return [
        {
            "id": str(p.id),
            "title": p.title,
            "short_description": p.short_description,
            "price": p.price,
            "brand": p.brand,
            "rating": p.rating,
            "sales": p.sales,
            "category": p.category,
            "stock": p.stock,
            "main_image": p.main_image,
            "created_at": p.created_at,
        }
        for p in products
    ]


# =====================================================
# ADMIN: CREATE PRODUCT
# =====================================================
@router.post("", dependencies=[Depends(require_admin)])
def create_product(payload: dict, db: Session = Depends(get_db)):
    product = Product(
        title=payload["title"],
        short_description=payload.get("short_description"),
        description=payload.get("description"),
        sku=payload.get("sku"),
        brand=payload.get("brand"),
        price=payload["price"],
        category=payload.get("category"),
        stock=payload.get("stock", 0),
        rating=payload.get("rating"),
        main_image=payload.get("img"),
        status="active",
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    return {
        "id": str(product.id),
        "title": product.title,
    }


# =====================================================
# ADMIN: UPLOAD PRODUCT IMAGE
# =====================================================
@router.post(
    "/admin/upload-image",
    dependencies=[Depends(require_admin)],
)
def upload_product_image(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)

    with open(path, "wb") as f:
        f.write(file.file.read())

    return {
        "url": f"/uploads/products/{filename}"
    }
