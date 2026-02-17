from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.models import User, Cart, CartItem, Product, ProductVariant
from app.dependencies import get_current_user

router = APIRouter(prefix="/cart", tags=["cart"])


# =====================================================
# Pydantic Schemas
# =====================================================

class AddToCartPayload(BaseModel):
    product_id: str
    variant_id: Optional[str] = None
    quantity: int = 1


class UpdateCartItemPayload(BaseModel):
    quantity: int


class MergeCartPayload(BaseModel):
    guest_cart_items: list  # List of {product_id, variant_id?, quantity}


# =====================================================
# HELPER: GET OR CREATE CART
# =====================================================
def get_or_create_cart(db: Session, user: User) -> Cart:
    """Get existing cart or create new one for user."""
    cart = db.query(Cart).filter(Cart.user_id == user.id).first()
    
    if not cart:
        cart = Cart(user_id=user.id)
        db.add(cart)
        db.commit()
        db.refresh(cart)
    
    return cart


# =====================================================
# USER: GET CART
# =====================================================
@router.get("", status_code=status.HTTP_200_OK)
def get_cart(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get current user's cart with items."""
    cart = (
        db.query(Cart)
        .options(
            joinedload(Cart.items)
            .joinedload(CartItem.product)
            .joinedload(Product.images)
        )
        .filter(Cart.user_id == user.id)
        .first()
    )

    if not cart:
        return {
            "cart_id": None,
            "items": [],
            "total_items": 0,
            "subtotal": 0,
        }

    items = []
    subtotal = 0

    for item in cart.items:
        # Check if product still exists and is active
        if not item.product or item.product.status != "active":
            continue

        item_total = item.price * item.quantity
        subtotal += item_total

        items.append({
            "id": str(item.id),
            "product_id": str(item.product_id),
            "variant_id": str(item.variant_id) if item.variant_id else None,
            "title": item.product.title,
            "image_url": item.product.images[0].image_url if item.product.images else None,
            "price": item.price,
            "quantity": item.quantity,
            "subtotal": item_total,
            "in_stock": item.product.in_stock,
            "stock": item.product.stock,
        })

    return {
        "cart_id": str(cart.id),
        "items": items,
        "total_items": len(items),
        "subtotal": subtotal,
    }


# =====================================================
# USER: ADD TO CART
# =====================================================
@router.post("/items", status_code=status.HTTP_201_CREATED)
def add_to_cart(
    payload: AddToCartPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add item to cart."""
    # Validate product exists
    product = db.query(Product).filter(
        Product.id == payload.product_id,
        Product.status == "active"
    ).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    # Check stock
    if payload.quantity > product.stock:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock. Available: {product.stock}"
        )

    # Get or create cart
    cart = get_or_create_cart(db, user)

    # Check if item already in cart
    existing_item = (
        db.query(CartItem)
        .filter(
            CartItem.cart_id == cart.id,
            CartItem.product_id == payload.product_id,
            CartItem.variant_id == payload.variant_id if payload.variant_id else CartItem.variant_id.is_(None)
        )
        .first()
    )

    if existing_item:
        # Update quantity
        new_quantity = existing_item.quantity + payload.quantity
        if new_quantity > product.stock:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot add more. Stock limit: {product.stock}"
            )
        existing_item.quantity = new_quantity
        db.commit()
        db.refresh(existing_item)
        
        return {
            "message": "Cart updated",
            "item_id": str(existing_item.id),
            "quantity": existing_item.quantity,
        }

    # Create new cart item
    cart_item = CartItem(
        cart_id=cart.id,
        product_id=payload.product_id,
        variant_id=payload.variant_id,
        quantity=payload.quantity,
        price=product.price,
    )

    db.add(cart_item)
    db.commit()
    db.refresh(cart_item)

    return {
        "message": "Item added to cart",
        "item_id": str(cart_item.id),
        "quantity": cart_item.quantity,
    }


# =====================================================
# USER: UPDATE CART ITEM
# =====================================================
@router.patch("/items/{item_id}", status_code=status.HTTP_200_OK)
def update_cart_item(
    item_id: str,
    payload: UpdateCartItemPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update cart item quantity."""
    cart = db.query(Cart).filter(Cart.user_id == user.id).first()

    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")

    item = (
        db.query(CartItem)
        .options(joinedload(CartItem.product))
        .filter(CartItem.id == item_id, CartItem.cart_id == cart.id)
        .first()
    )

    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")

    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    # Check stock
    if payload.quantity > item.product.stock:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock. Available: {item.product.stock}"
        )

    item.quantity = payload.quantity
    db.commit()
    db.refresh(item)

    return {
        "message": "Cart item updated",
        "item_id": str(item.id),
        "quantity": item.quantity,
    }


# =====================================================
# USER: REMOVE CART ITEM
# =====================================================
@router.delete("/items/{item_id}", status_code=status.HTTP_200_OK)
def remove_cart_item(
    item_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove item from cart."""
    cart = db.query(Cart).filter(Cart.user_id == user.id).first()

    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")

    item = (
        db.query(CartItem)
        .filter(CartItem.id == item_id, CartItem.cart_id == cart.id)
        .first()
    )

    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")

    db.delete(item)
    db.commit()

    return {"message": "Item removed from cart"}


# =====================================================
# USER: CLEAR CART
# =====================================================
@router.delete("/clear", status_code=status.HTTP_200_OK)
def clear_cart(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clear all items from cart."""
    cart = db.query(Cart).filter(Cart.user_id == user.id).first()

    if not cart:
        return {"message": "Cart already empty"}

    db.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
    db.commit()

    return {"message": "Cart cleared"}


# =====================================================
# USER: MERGE CART (For guest -> user conversion)
# =====================================================
@router.post("/merge", status_code=status.HTTP_200_OK)
def merge_cart(
    payload: MergeCartPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Merge guest cart items into user cart after login.
    This is useful for when a guest adds items, then logs in.
    """
    if not payload.guest_cart_items:
        return {"message": "No items to merge"}

    cart = get_or_create_cart(db, user)
    merged_count = 0
    errors = []

    for guest_item in payload.guest_cart_items:
        try:
            product_id = guest_item.get("product_id")
            variant_id = guest_item.get("variant_id")
            quantity = guest_item.get("quantity", 1)

            # Validate product
            product = db.query(Product).filter(
                Product.id == product_id,
                Product.status == "active"
            ).first()

            if not product:
                errors.append(f"Product {product_id} not found")
                continue

            # Check if already in cart
            existing = (
                db.query(CartItem)
                .filter(
                    CartItem.cart_id == cart.id,
                    CartItem.product_id == product_id,
                    CartItem.variant_id == variant_id if variant_id else CartItem.variant_id.is_(None)
                )
                .first()
            )

            if existing:
                # Merge quantities
                new_qty = min(existing.quantity + quantity, product.stock)
                existing.quantity = new_qty
            else:
                # Add new item
                cart_item = CartItem(
                    cart_id=cart.id,
                    product_id=product_id,
                    variant_id=variant_id,
                    quantity=min(quantity, product.stock),
                    price=product.price,
                )
                db.add(cart_item)

            merged_count += 1

        except Exception as e:
            errors.append(str(e))

    db.commit()

    return {
        "message": f"Merged {merged_count} items",
        "merged_count": merged_count,
        "errors": errors if errors else None,
    }
