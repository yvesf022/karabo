from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product
from app.dependencies import require_admin

router = APIRouter(prefix="/products", tags=["products"])


# =============================
# PUBLIC: LIST PRODUCTS
# =============================
@router.get("")
def list_products(db: Session = Depends(get_db)):
    products = db.query(Product).all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "price": p.price,
            "img": p.img,
            "category": p.category,
            "rating": p.rating,
            "stock": p.stock,
            "in_stock": p.in_stock,
        }
        for p in products
    ]


# =============================
# ADMIN: ADD PRODUCT
# =============================
@router.post("")
def add_product(
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    title = payload.get("title")
    price = payload.get("price")
    category = payload.get("category")
    img = payload.get("img")
    rating = payload.get("rating", 0)
    stock = payload.get("stock", 0)

    if not title or price is None or not category or not img:
        raise HTTPException(
            status_code=400,
            detail="Missing required product fields",
        )

    product = Product(
        title=title,
        price=price,
        category=category,
        img=img,
        rating=rating,
        stock=stock,
        in_stock=stock > 0,
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    return {
        "id": product.id,
        "message": "Product created",
    }


# =============================
# ADMIN: UPDATE PRODUCT
# =============================
@router.post("/{product_id}")
def update_product(
    product_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(404, "Product not found")

    stock_updated = False

    for field in ["title", "price", "category", "img", "rating", "stock"]:
        if field in payload:
            setattr(product, field, payload[field])
            if field == "stock":
                stock_updated = True

    if stock_updated:
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
        raise HTTPException(status_code=404, detail="Product not found")

    db.delete(product)
    db.commit()

    return {"message": "Product deleted"}
