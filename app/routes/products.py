import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product
from app.dependencies import require_admin

router = APIRouter(prefix="/products", tags=["products"])

UPLOAD_DIR = "uploads/products"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# -----------------------------
# PUBLIC: LIST PRODUCTS
# -----------------------------
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
        }
        for p in products
    ]


# -----------------------------
# ADMIN: ADD PRODUCT
# -----------------------------
@router.post("")
def add_product(
    title: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    rating: float = Form(0),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    ext = os.path.splitext(image.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(image.file.read())

    product = Product(
        title=title,
        price=price,
        category=category,
        rating=rating,
        img=f"/{UPLOAD_DIR}/{filename}",
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    return {
        "id": product.id,
        "message": "Product created",
    }


# -----------------------------
# ADMIN: DELETE PRODUCT
# -----------------------------
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
