from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
)
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
import uuid
import os

from app.database import get_db
from app.models import Product, ProductImage
from app.dependencies import require_admin

router = APIRouter(prefix="/products", tags=["products"])

UPLOAD_DIR = "uploads/products"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =====================================================
# PUBLIC: LIST PRODUCTS (WITH IMAGES)
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
            | func.to_tsvector("english", Product.short_description).match(search_query)
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
            "images": [img.image_url for img in p.images],
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
        compare_price=payload.get("compare_price"),
        category=payload.get("category"),
        stock=payload.get("stock", 0),
        rating=payload.get("rating"),
        main_image=payload.get("img"),
        status="active",
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    return {"id": str(product.id), "title": product.title}


# =====================================================
# ADMIN: UPDATE PRODUCT (PATCH)
# =====================================================
@router.patch(
    "/admin/{product_id}",
    dependencies=[Depends(require_admin)],
)
def update_product(
    product_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    editable_fields = {
        "title",
        "short_description",
        "description",
        "sku",
        "brand",
        "price",
        "compare_price",
        "category",
        "stock",
        "rating",
        "in_stock",
        "status",
        "main_image",
        "specs",
    }

    updated = False
    for key, value in payload.items():
        if key in editable_fields:
            setattr(product, key, value)
            updated = True

    if not updated:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    db.commit()
    db.refresh(product)

    return {
        "id": str(product.id),
        "title": product.title,
        "status": product.status,
        "price": product.price,
        "stock": product.stock,
        "main_image": product.main_image,
        "updated_at": product.updated_at,
    }


# =====================================================
# ADMIN: SOFT DELETE PRODUCT
# =====================================================
@router.post(
    "/admin/{product_id}/disable",
    dependencies=[Depends(require_admin)],
)
def disable_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.status = "inactive"
    db.commit()

    return {"id": str(product.id), "status": product.status}


# =====================================================
# ADMIN: RESTORE PRODUCT
# =====================================================
@router.post(
    "/admin/{product_id}/restore",
    dependencies=[Depends(require_admin)],
)
def restore_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.status = "active"
    db.commit()

    return {"id": str(product.id), "status": product.status}


# =====================================================
# ADMIN: GET PRODUCT DETAILS (EDIT SCREEN)
# =====================================================
@router.get(
    "/admin/{product_id}",
    dependencies=[Depends(require_admin)],
)
def get_product_admin(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return {
        "id": str(product.id),
        "title": product.title,
        "short_description": product.short_description,
        "description": product.description,
        "sku": product.sku,
        "brand": product.brand,
        "price": product.price,
        "compare_price": product.compare_price,
        "category": product.category,
        "stock": product.stock,
        "in_stock": product.in_stock,
        "rating": product.rating,
        "status": product.status,
        "main_image": product.main_image,
        "specs": product.specs,
        "images": [
            {
                "id": str(img.id),
                "url": img.image_url,
                "position": img.position,
            }
            for img in product.images
        ],
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }


# =====================================================
# ADMIN: UPLOAD PRODUCT IMAGE
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
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)

    with open(path, "wb") as f:
        f.write(file.file.read())

    position = db.query(ProductImage).filter(
        ProductImage.product_id == product.id
    ).count()

    image = ProductImage(
        product_id=product.id,
        image_url=f"/uploads/products/{filename}",
        position=position,
    )

    db.add(image)
    db.commit()

    return {"url": image.image_url, "position": image.position}


# =====================================================
# ADMIN: DELETE PRODUCT IMAGE
# =====================================================
@router.delete(
    "/admin/images/{image_id}",
    dependencies=[Depends(require_admin)],
)
def delete_product_image(image_id: str, db: Session = Depends(get_db)):
    image = db.query(ProductImage).filter(ProductImage.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    file_path = image.image_url.lstrip("/")
    if os.path.exists(file_path):
        os.remove(file_path)

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
        raise HTTPException(status_code=400, detail="Invalid image list")

    image_map = {str(img.id): img for img in images}

    for position, image_id in enumerate(image_ids):
        image_map[image_id].position = position

    db.commit()

    return {"detail": "Images reordered"}


# =====================================================
# ADMIN: SET IMAGE AS MAIN IMAGE
# =====================================================
@router.post(
    "/admin/images/{image_id}/set-main",
    dependencies=[Depends(require_admin)],
)
def set_main_image(image_id: str, db: Session = Depends(get_db)):
    image = db.query(ProductImage).filter(ProductImage.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    product = db.query(Product).filter(Product.id == image.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.main_image = image.image_url
    db.commit()

    return {
        "product_id": str(product.id),
        "main_image": product.main_image,
    }
