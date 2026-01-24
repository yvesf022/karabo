from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product
import uuid, os

router = APIRouter()

@router.get("")
def list_products(db: Session = Depends(get_db)):
    products = db.query(Product).all()
    return [{**p.__dict__, "_id": str(p.id)} for p in products]

@router.post("")
def add_product(
    title: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    fname = f"products/{uuid.uuid4()}-{image.filename}"
    with open(f"uploads/{fname}", "wb") as f:
        f.write(image.file.read())

    p = Product(
        title=title,
        description=description,
        price=price,
        category=category,
        image_url=f"/uploads/{fname}"
    )
    db.add(p)
    db.commit()
    return {"id": str(p.id)}
