from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Category, Brand

router = APIRouter(tags=["categories-brands"])

@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    categories = db.query(Category).filter(Category.is_active == True).order_by(Category.position).all()
    return [{"id": str(c.id), "name": c.name, "slug": c.slug, "image_url": c.image_url, "parent_id": str(c.parent_id) if c.parent_id else None} for c in categories]

@router.get("/categories/{category_id}")
def get_category(category_id: str, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(404, "Category not found")
    return {"id": str(cat.id), "name": cat.name, "slug": cat.slug, "description": cat.description, "image_url": cat.image_url}

@router.get("/brands")
def get_brands(db: Session = Depends(get_db)):
    brands = db.query(Brand).filter(Brand.is_active == True).all()
    return [{"id": str(b.id), "name": b.name, "slug": b.slug, "logo_url": b.logo_url} for b in brands]
