from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import User, RecentlyViewed, Product
from app.dependencies import get_current_user
from sqlalchemy import func

router = APIRouter(prefix="/users/me/recently-viewed", tags=["recently-viewed"])


def _get_image(product: Product) -> str | None:
    """Return primary image URL, or first available image, or None."""
    if not product.images:
        return None
    primary = next((i.image_url for i in product.images if i.is_primary), None)
    return primary or product.images[0].image_url


@router.get("", status_code=status.HTTP_200_OK)
def get_recently_viewed(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = (
        db.query(RecentlyViewed)
        # ✅ FIX: joinedload the product's images too so we can return main_image
        .options(joinedload(RecentlyViewed.product).joinedload(Product.images))
        .filter(RecentlyViewed.user_id == user.id)
        .order_by(RecentlyViewed.viewed_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "product_id":   str(i.product_id),
            "title":        i.product.title        if i.product else None,
            "price":        i.product.price        if i.product else None,
            "compare_price": i.product.compare_price if i.product else None,
            "brand":        i.product.brand        if i.product else None,
            "category":     i.product.category     if i.product else None,
            "in_stock":     (i.product.stock > 0)  if i.product else False,
            # ✅ FIX: main_image was missing — cards showed placeholder icon
            "main_image":   _get_image(i.product)  if i.product else None,
            "viewed_at":    i.viewed_at,
        }
        for i in items
        if i.product
    ]


@router.delete("", status_code=status.HTTP_200_OK)
def clear_recently_viewed(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    db.query(RecentlyViewed).filter(RecentlyViewed.user_id == user.id).delete()
    db.commit()
    return {"message": "Recently viewed cleared"}