from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product, ProductStatus
from app.dependencies import require_admin

router = APIRouter(prefix="/products", tags=["products"])


# =============================
# PUBLIC: LIST PRODUCTS
# =============================
@router.get("")
def list_products(db: Session = Depends(get_db)):
    products = (
        db.query(Product)
        .filter(Product.status == ProductStatus.active)
        .all()
    )

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


# =============================
# PUBLIC: PRODUCT DETAIL
# =============================
@router.get("/{product_id}")
def product_detail(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product or product.status != ProductStatus.active:
        raise HTTPException(404, "Product not found")

    return {
        "id": product.id,
        "title": product.title,
        "short_description": product.short_description,
        "description": product.description,
        "price": product.price,
        "compare_price": product.compare_price,
        "sku": product.sku,
        "main_image": product.main_image,
        "images": product.images,
        "category": product.category,
        "specs": product.specs,
        "stock": product.stock,
        "in_stock": product.in_stock,
    }


# =============================
# ADMIN: CREATE PRODUCT
# =============================
@router.post("")
def create_product(
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    required = ["title", "sku", "price", "category", "main_image"]
    for field in required:
        if field not in payload:
            raise HTTPException(400, f"Missing field: {field}")

    product = Product(
        title=payload["title"],
        short_description=payload.get("short_description"),
        description=payload.get("description"),
        sku=payload["sku"],
        price=payload["price"],
        compare_price=payload.get("compare_price"),
        main_image=payload["main_image"],
        images=payload.get("images", []),
        category=payload["category"],
        specs=payload.get("specs", {}),
        stock=payload.get("stock", 0),
        in_stock=payload.get("stock", 0) > 0,
        status=payload.get("status", ProductStatus.active),
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    return {"id": product.id}


# =============================
# ADMIN: UPDATE PRODUCT
# =============================
@router.put("/{product_id}")
def update_product(
    product_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")

    for field in [
        "title",
        "short_description",
        "description",
        "sku",
        "price",
        "compare_price",
        "main_image",
        "images",
        "category",
        "specs",
        "status",
        "stock",
    ]:
        if field in payload:
            setattr(product, field, payload[field])

    if "stock" in payload:
        product.in_stock = product.stock > 0

    db.commit()
    return {"message": "Product updated"}


# =============================
# ADMIN: DELETE PRODUCT
# =============================
@router.delete("/{product_id}")
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")

    db.delete(product)
    db.commit()
    return {"message": "Product deleted"}
