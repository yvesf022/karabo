from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import User, Wishlist, Product, Cart, CartItem
from app.dependencies import get_current_user

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


# =====================================================
# USER: GET WISHLIST
# =====================================================
@router.get("", status_code=status.HTTP_200_OK)
def get_wishlist(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get user's wishlist."""
    wishlist_items = (
        db.query(Wishlist)
        .options(joinedload(Wishlist.product).joinedload(Product.images))
        .filter(Wishlist.user_id == user.id)
        .order_by(Wishlist.created_at.desc())
        .all()
    )

    items = []
    for item in wishlist_items:
        if not item.product or item.product.status != "active":
            continue

        items.append({
            "product_id": str(item.product_id),
            "title": item.product.title,
            "price": item.product.price,
            "compare_price": item.product.compare_price,
            "image_url": item.product.images[0].image_url if item.product.images else None,
            "in_stock": item.product.in_stock,
            "rating": item.product.rating,
            "added_at": item.created_at,
        })

    return {
        "items": items,
        "total": len(items),
    }


# =====================================================
# USER: ADD TO WISHLIST
# =====================================================
@router.post("/{product_id}", status_code=status.HTTP_201_CREATED)
def add_to_wishlist(
    product_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add product to wishlist."""
    # Check product exists
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if already in wishlist
    existing = (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user.id, Wishlist.product_id == product_id)
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="Product already in wishlist")

    wishlist_item = Wishlist(user_id=user.id, product_id=product_id)
    db.add(wishlist_item)
    db.commit()

    return {"message": "Added to wishlist", "product_id": product_id}


# =====================================================
# USER: REMOVE FROM WISHLIST
# =====================================================
@router.delete("/{product_id}", status_code=status.HTTP_200_OK)
def remove_from_wishlist(
    product_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove product from wishlist."""
    item = (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user.id, Wishlist.product_id == product_id)
        .first()
    )

    if not item:
        raise HTTPException(status_code=404, detail="Product not in wishlist")

    db.delete(item)
    db.commit()

    return {"message": "Removed from wishlist"}


# =====================================================
# USER: MOVE TO CART
# =====================================================
@router.post("/{product_id}/move-to-cart", status_code=status.HTTP_200_OK)
def move_to_cart(
    product_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Move item from wishlist to cart."""
    # Check wishlist item exists
    wishlist_item = (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user.id, Wishlist.product_id == product_id)
        .first()
    )

    if not wishlist_item:
        raise HTTPException(status_code=404, detail="Product not in wishlist")

    # Get product
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or product.status != "active":
        raise HTTPException(status_code=400, detail="Product not available")

    if not product.in_stock:
        raise HTTPException(status_code=400, detail="Product out of stock")

    # Get or create cart
    cart = db.query(Cart).filter(Cart.user_id == user.id).first()
    if not cart:
        cart = Cart(user_id=user.id)
        db.add(cart)
        db.commit()
        db.refresh(cart)

    # Check if already in cart
    existing_cart_item = (
        db.query(CartItem)
        .filter(CartItem.cart_id == cart.id, CartItem.product_id == product_id)
        .first()
    )

    if existing_cart_item:
        existing_cart_item.quantity += 1
    else:
        cart_item = CartItem(
            cart_id=cart.id,
            product_id=product_id,
            quantity=1,
            price=product.price,
        )
        db.add(cart_item)

    # Remove from wishlist
    db.delete(wishlist_item)
    db.commit()

    return {"message": "Moved to cart", "product_id": product_id}
