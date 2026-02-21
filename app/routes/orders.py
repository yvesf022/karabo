from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import (
    Order, OrderStatus, OrderItem, OrderTracking,
    ShippingStatus, Payment, PaymentStatus,
    Product, ProductVariant, ProductImage,
    User, Cart, CartItem,
)

router = APIRouter(prefix="/orders", tags=["orders"])


# =====================================================
# PYDANTIC SCHEMAS
# =====================================================

class OrderItemInput(BaseModel):
    product_id: str
    variant_id: Optional[str] = None
    quantity: int
    price: float

class CreateOrderPayload(BaseModel):
    items: List[OrderItemInput]
    shipping_address: Optional[dict] = None
    notes: Optional[str] = None
    coupon_code: Optional[str] = None


# =====================================================
# HELPERS
# =====================================================

def _serialize_order_summary(o: Order) -> dict:
    return {
        "id":               str(o.id),
        "total_amount":     o.total_amount,
        "status":           o.status,
        "shipping_status":  o.shipping_status,
        "shipping_address": o.shipping_address,
        "notes":            o.notes,
        "created_at":       o.created_at,
        "updated_at":       o.updated_at,
        "tracking_number":  o.tracking.tracking_number if o.tracking else None,
        # Include lightweight item list so list page can show real product thumbnails
        "items": [
            {
                "id":         str(i.id),
                "product_id": str(i.product_id) if i.product_id else None,
                "title":      i.product_title,
                "quantity":   i.quantity,
                "price":      i.price,
                "subtotal":   i.subtotal,
                "product": {
                    "id":         str(i.product_id),
                    "main_image": i.product.main_image if i.product else None,
                    "images": [
                        {"image_url": img.image_url, "is_primary": img.is_primary}
                        for img in (i.product.images[:1] if i.product and i.product.images else [])
                    ],
                } if i.product else None,
            }
            for i in (o.items if hasattr(o, "items") and o.items else [])
        ],
    }


def _serialize_order_detail(o: Order, include_admin_fields: bool = False) -> dict:
    data = {
        "id":               str(o.id),
        "user_id":          str(o.user_id),
        "total_amount":     o.total_amount,
        "status":           o.status,
        "shipping_status":  o.shipping_status,
        "shipping_address": o.shipping_address,
        "notes":            o.notes,
        "created_at":       o.created_at,
        "updated_at":       o.updated_at,
        "items": [
            {
                "id":            str(i.id),
                "product_id":    str(i.product_id) if i.product_id else None,
                "title":         i.product_title,   # alias so frontend can use item.title
                "product_title": i.product_title,
                "variant_title": i.variant_title,
                "quantity":      i.quantity,
                "price":         i.price,
                "subtotal":      i.subtotal,
                # Inline product snapshot — frontend never needs a second request for images
                "product": {
                    "id":         str(i.product_id),
                    "main_image": i.product.main_image if i.product else None,
                    "images": [
                        {"image_url": img.image_url, "is_primary": img.is_primary}
                        for img in (i.product.images[:3] if i.product and i.product.images else [])
                    ],
                } if i.product else None,
                "variant": {
                    "id":         str(i.variant.id),
                    "title":      i.variant.title,
                    "attributes": i.variant.attributes or {},
                    "image_url":  i.variant.image_url,
                } if i.variant else None,
            }
            for i in o.items
        ] if hasattr(o, "items") and o.items else [],
        "payments": [
            {
                "id":              str(p.id),
                "amount":          p.amount,
                "status":          p.status,
                "method":          p.method,
                "reference_number": getattr(p, "reference_number", None),
                "proof": (
                    {
                        "id":          str(p.proof.id),
                        "file_url":    p.proof.file_url,
                        "uploaded_at": p.proof.uploaded_at,
                    }
                    if p.proof else None
                ),
                "reviewed_at": p.reviewed_at,
                "created_at":  p.created_at,
                **({"admin_notes": p.admin_notes, "reviewed_by": str(p.reviewed_by) if p.reviewed_by else None}
                   if include_admin_fields else {}),
            }
            for p in o.payments
        ],
    }
    if o.tracking:
        data["tracking"] = {
            "carrier":           o.tracking.carrier,
            "tracking_number":   o.tracking.tracking_number,
            "tracking_url":      o.tracking.tracking_url,
            "estimated_delivery": o.tracking.estimated_delivery,
            "actual_delivery":   o.tracking.actual_delivery,
        }
    return data


# =====================================================
# USER: CREATE ORDER
# =====================================================

@router.post("", status_code=201)
def create_order(
    payload: CreateOrderPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Creates an order from a list of items.
    Validates stock, snapshots prices, deducts stock, clears cart.
    """
    if not payload.items:
        raise HTTPException(400, "Order must contain at least one item")

    items_data = []
    total      = 0.0

    for item in payload.items:
        product = db.query(Product).filter(
            Product.id == item.product_id,
            Product.is_deleted == False,
            Product.status == "active",
        ).first()
        if not product:
            raise HTTPException(404, f"Product {item.product_id} not found or unavailable")

        # Variant check
        variant       = None
        variant_title = None
        price         = item.price  # frontend sends price as snapshot

        if item.variant_id:
            variant = db.query(ProductVariant).filter(
                ProductVariant.id == item.variant_id,
                ProductVariant.product_id == item.product_id,
                ProductVariant.is_deleted == False,
                ProductVariant.is_active == True,
            ).first()
            if not variant:
                raise HTTPException(404, f"Variant {item.variant_id} not found")
            variant_title = variant.title
            price         = variant.price  # always use server-side price

            if variant.stock < item.quantity:
                raise HTTPException(400, f"Not enough stock for variant '{variant.title}'. Available: {variant.stock}")
        else:
            price = product.price  # server-side price
            if product.stock < item.quantity:
                raise HTTPException(400, f"Not enough stock for '{product.title}'. Available: {product.stock}")

        subtotal = round(price * item.quantity, 2)
        total   += subtotal
        items_data.append({
            "product":       product,
            "variant":       variant,
            "variant_title": variant_title,
            "quantity":      item.quantity,
            "price":         price,
            "subtotal":      subtotal,
        })

    total = round(total, 2)

    # Create order
    order = Order(
        user_id          = user.id,
        total_amount     = total,
        status           = OrderStatus.pending,
        shipping_status  = ShippingStatus.pending,
        shipping_address = payload.shipping_address,
        notes            = payload.notes,
        is_deleted       = False,
    )
    db.add(order)
    db.flush()

    # Create order items + deduct stock
    for item_data in items_data:
        db.add(OrderItem(
            order_id       = order.id,
            product_id     = item_data["product"].id,
            variant_id     = item_data["variant"].id if item_data["variant"] else None,
            product_title  = item_data["product"].title,
            variant_title  = item_data["variant_title"],
            quantity       = item_data["quantity"],
            price          = item_data["price"],
            subtotal       = item_data["subtotal"],
        ))

        # Deduct stock
        if item_data["variant"]:
            item_data["variant"].stock    -= item_data["quantity"]
            item_data["variant"].in_stock  = item_data["variant"].stock > 0
        else:
            item_data["product"].stock    -= item_data["quantity"]
            item_data["product"].in_stock  = item_data["product"].stock > 0

    # Clear user's cart after order is placed
    cart = db.query(Cart).filter(Cart.user_id == user.id).first()
    if cart:
        db.query(CartItem).filter(CartItem.cart_id == cart.id).delete(synchronize_session=False)

    db.commit()
    db.refresh(order)

    return {
        "order_id":    str(order.id),
        "total":       order.total_amount,
        "status":      order.status,
        "items_count": len(items_data),
    }


# =====================================================
# USER: MY ORDERS (paginated)
# =====================================================

@router.get("/my")
def my_orders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    status_filter: Optional[str] = Query(None, alias="status"),
    page:     int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    query = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product).joinedload(Product.images),
            joinedload(Order.tracking),
        )
        .filter(Order.user_id == user.id, Order.is_deleted == False)
    )
    if status_filter:
        try:
            query = query.filter(Order.status == OrderStatus(status_filter))
        except ValueError:
            raise HTTPException(400, f"Invalid status: '{status_filter}'")

    total  = query.count()
    orders = query.order_by(Order.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    (total + per_page - 1) // per_page,
        "results":  [_serialize_order_summary(o) for o in orders],
    }


# =====================================================
# USER: CANCEL OWN ORDER
# =====================================================

@router.post("/my/{order_id}/cancel")
def cancel_my_order(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == user.id,
        Order.is_deleted == False,
    ).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.pending:
        raise HTTPException(400, f"Cannot cancel an order in status '{order.status.value}'. Only pending orders can be cancelled.")

    order.status     = OrderStatus.cancelled
    order.updated_at = datetime.now(timezone.utc)

    # Restore stock
    for item in order.items:
        if item.variant_id:
            variant = db.query(ProductVariant).filter(ProductVariant.id == item.variant_id).first()
            if variant:
                variant.stock    += item.quantity
                variant.in_stock  = variant.stock > 0
        elif item.product_id:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.stock    += item.quantity
                product.in_stock  = product.stock > 0

    # Cancel any pending payment
    for payment in order.payments:
        if payment.status in (PaymentStatus.pending, PaymentStatus.on_hold):
            payment.status = PaymentStatus.rejected

    db.commit()
    return {"message": "Order cancelled", "order_id": order_id}


# =====================================================
# ADMIN: LIST ALL ORDERS (paginated + filterable)
# =====================================================

# ⚠️  ROUTE ORDER CRITICAL: /admin and /admin/{order_id}
# must be registered BEFORE /{order_id}

@router.get("/admin")
def admin_orders(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    status_filter: Optional[str] = Query(None, alias="status"),
    shipping_filter: Optional[str] = Query(None, alias="shipping"),
    search: Optional[str] = None,
    include_deleted: bool = False,
    page:     int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    query = db.query(Order)
    if not include_deleted:
        query = query.filter(Order.is_deleted == False)
    if status_filter:
        try:
            query = query.filter(Order.status == OrderStatus(status_filter))
        except ValueError:
            raise HTTPException(400, f"Invalid status: '{status_filter}'")
    if shipping_filter:
        try:
            query = query.filter(Order.shipping_status == ShippingStatus(shipping_filter))
        except ValueError:
            raise HTTPException(400, f"Invalid shipping status: '{shipping_filter}'")

    total  = query.count()
    orders = query.order_by(Order.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    # Status summary counts
    from sqlalchemy import func
    stats = db.query(Order.status, func.count(Order.id)).filter(Order.is_deleted == False).group_by(Order.status).all()

    return {
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    (total + per_page - 1) // per_page,
        "stats":    {s.value: c for s, c in stats},
        "results": [
            {
                "id":               str(o.id),
                "user_id":          str(o.user_id),
                "total_amount":     o.total_amount,
                "status":           o.status,
                "shipping_status":  o.shipping_status,
                "notes":            o.notes,
                "created_at":       o.created_at,
                "updated_at":       o.updated_at,
            }
            for o in orders
        ],
    }


# =====================================================
# ADMIN: UPDATE SHIPPING STATUS
# =====================================================

@router.post("/admin/{order_id}/shipping")
def update_shipping(
    order_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.paid:
        raise HTTPException(400, "Cannot update shipping before payment is approved")
    try:
        order.shipping_status = ShippingStatus(payload.get("status"))
    except Exception:
        raise HTTPException(400, f"Invalid shipping status. Valid values: {[s.value for s in ShippingStatus]}")
    order.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "message":        "Shipping updated",
        "order_id":       str(order.id),
        "shipping_status": order.shipping_status,
    }


# =====================================================
# ADMIN: GET SINGLE ORDER DETAIL
# ⚠️  Must be BEFORE user /{order_id}
# =====================================================

@router.get("/admin/{order_id}")
def admin_get_order_detail(
    order_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    order = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product).joinedload(Product.images),
            joinedload(Order.items).joinedload(OrderItem.variant),
            joinedload(Order.payments).joinedload(Payment.proof),
            joinedload(Order.tracking),
        )
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(404, "Order not found")
    return _serialize_order_detail(order, include_admin_fields=True)


# =====================================================
# USER: GET SINGLE ORDER DETAIL
# ⚠️  Wildcard — must be LAST
# =====================================================

@router.get("/{order_id}")
def get_my_order_detail(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product).joinedload(Product.images),
            joinedload(Order.items).joinedload(OrderItem.variant),
            joinedload(Order.payments).joinedload(Payment.proof),
            joinedload(Order.tracking),
        )
        .filter(Order.id == order_id, Order.user_id == user.id, Order.is_deleted == False)
        .first()
    )
    if not order:
        raise HTTPException(404, "Order not found")
    return _serialize_order_detail(order)