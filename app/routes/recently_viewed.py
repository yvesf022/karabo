from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import User, RecentlyViewed, Product
from app.dependencies import get_current_user
from sqlalchemy import func

router = APIRouter(prefix="/users/me/recently-viewed", tags=["recently-viewed"])

@router.get("", status_code=status.HTTP_200_OK)
def get_recently_viewed(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = db.query(RecentlyViewed).options(joinedload(RecentlyViewed.product)).filter(RecentlyViewed.user_id == user.id).order_by(RecentlyViewed.viewed_at.desc()).limit(20).all()
    return [{"product_id": str(i.product_id), "title": i.product.title if i.product else None, "price": i.product.price if i.product else None, "viewed_at": i.viewed_at} for i in items if i.product]

@router.delete("", status_code=status.HTTP_200_OK)
def clear_recently_viewed(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(RecentlyViewed).filter(RecentlyViewed.user_id == user.id).delete()
    db.commit()
    return {"message": "Recently viewed cleared"}
