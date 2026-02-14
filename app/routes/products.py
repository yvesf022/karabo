from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    status,
)
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List

from app.database import get_db
from app.models import Product, ProductImage, ProductStatus
from app.dependencies import require_admin
from app.uploads.service import handle_upload

router = APIRouter(prefix="/products", tags=["products"])


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
    page = max(page, 1)
    per_page = min(max(per_page, 1), 100)

    query = db.query(Product).filter(Product.status == ProductStatus.active)

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
        query = query.filter(
            Product.stock > 0 if in_stock else Product.stock <= 0
        )
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

    products = (
        query.offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

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
            "main_image": p.images[0].image_url if p.images else None,
            "images": [img.image_url for img in p.images],
            "created_at": p.created_at,
        }
        for p in products
    ]


# =====================================================
# PUBLIC: GET SINGLE PRODUCT  ✅ SAFE ADDITION
# =====================================================
@router.get("/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            Product.status == ProductStatus.active,
        )
        .first()
    )

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return {
        "id": str(product.id),
        "title": product.title,
        "short_description": product.short_description,
        "description": product.description,
        "price": product.price,
        "compare_price": product.compare_price,
        "brand": product.brand,
        "rating": product.rating,
        "sales": product.sales,
        "category": product.category,
        "stock": product.stock,
        "in_stock": product.stock > 0,
        "main_image": product.images[0].image_url if product.images else None,
        "images": [img.image_url for img in product.images],
        "created_at": product.created_at,
    }


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
        compare_price=payload.get("compare_price"),
        category=payload.get("category"),
        stock=payload.get("stock", 0),
        rating=payload.get("rating"),
        status=ProductStatus.active,
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    return {"id": str(product.id), "title": product.title}


# =====================================================
# ADMIN: UPLOAD PRODUCT IMAGE (CENTRALIZED)
# =====================================================
@router.post(
    "/admin/{product_id}/images",
    dependencies=[Depends(require_admin)],
)
def upload_product_image(
    product_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    image_url = handle_upload(
        file=file,
        folder="products",
        owner_id=str(product.id),
    )

    position = (
        db.query(ProductImage)
        .filter(ProductImage.product_id == product.id)
        .count()
    )

    image = ProductImage(
        product_id=product.id,
        image_url=image_url,
        position=position,
    )

    db.add(image)
    db.commit()
    db.refresh(image)

    return {
        "url": image.image_url,
        "position": image.position,
    }


# =====================================================
# ADMIN: DELETE PRODUCT IMAGE
# =====================================================
@router.delete(
    "/admin/images/{image_id}",
    dependencies=[Depends(require_admin)],
)
def delete_product_image(image_id: str, db: Session = Depends(get_db)):
    image = (
        db.query(ProductImage)
        .filter(ProductImage.id == image_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    product_id = image.product_id
    db.delete(image)
    db.commit()

    images = (
        db.query(ProductImage)
        .filter(ProductImage.product_id == product_id)
        .order_by(ProductImage.position)
        .all()
    )

    for idx, img in enumerate(images):
        img.position = idx

    db.commit()

    return {"detail": "Image deleted"}


# =====================================================
# ADMIN: REORDER PRODUCT IMAGES
# =====================================================
@router.put(
    "/admin/{product_id}/images/reorder",
    dependencies=[Depends(require_admin)],
)
def reorder_product_images(
    product_id: str,
    image_ids: List[str],
    db: Session = Depends(get_db),
):
    images = (
        db.query(ProductImage)
        .filter(
            ProductImage.product_id == product_id,
            ProductImage.id.in_(image_ids),
        )
        .all()
    )

    if len(images) != len(image_ids):
        raise HTTPException(
            status_code=400,
            detail="Invalid image list",
        )

    image_map = {str(img.id): img for img in images}

    for position, image_id in enumerate(image_ids):
        image_map[image_id].position = position

    db.commit()

    return {"detail": "Images reordered"}


# =====================================================
# ADMIN: SET MAIN IMAGE
# =====================================================
@router.post(
    "/admin/images/{image_id}/set-main",
    dependencies=[Depends(require_admin)],
)
def set_main_image(image_id: str, db: Session = Depends(get_db)):
    image = (
        db.query(ProductImage)
        .filter(ProductImage.id == image_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    images = (
        db.query(ProductImage)
        .filter(ProductImage.product_id == image.product_id)
        .order_by(ProductImage.position)
        .all()
    )

    for img in images:
        img.position = 1

    image.position = 0
    db.commit()

    return {"detail": "Main image set"}
