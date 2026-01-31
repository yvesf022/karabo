from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import (
    Order,
    OrderStatus,
    ShippingStatus,
    PaymentStatus,
)

router = APIRouter(prefix="/orders", tags=["orders"])


# =============================
# USER: CREATE ORDER
# =============================
@router.post("")
def create_order(
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    items = payload.get("items")
    total = payload.get("total_amount")

    if not items or not total:
        raise HTTPException(400, "Invalid order data")

    order = Order(
        user_id=user.id,
        items=items,
        total_amount=total,
        order_status=OrderStatus.awaiting_payment,  # 🔑 manual payment flow
        shipping_status=ShippingStatus.created,
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "order_id": order.id,
        "order_status": order.order_status,
    }


# =============================
# USER: MY ORDERS
# =============================
@router.get("/my")
def my_orders(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    orders = (
        db.query(Order)
        .filter(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .all()
    )

    return [
        {
            "id": o.id,
            "total_amount": o.total_amount,
            "order_status": o.order_status,
            "payment_status": o.payment.status if o.payment else None,
            "shipping_status": o.shipping_status,
            "created_at": o.created_at,
        }
        for o in orders
    ]


# =============================
# ADMIN: LIST ORDERS
# =============================
@router.get("/admin")
def admin_orders(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    orders = db.query(Order).order_by(Order.created_at.desc()).all()

    return [
        {
            "id": o.id,
            "total_amount": o.total_amount,
            "order_status": o.order_status,
            "payment_status": o.payment.status if o.payment else None,
            "shipping_status": o.shipping_status,
            "created_at": o.created_at,
        }
        for o in orders
    ]


# =============================
# ADMIN: UPDATE SHIPPING
# =============================
@router.post("/admin/{order_id}/shipping")
def update_shipping(
    order_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")

    # 🔒 HARD BLOCK: shipping ONLY allowed after payment approval
    if order.order_status != OrderStatus.paid:
        raise HTTPException(
            400,
            "Order cannot be shipped before payment is approved",
        )

    new_status = payload.get("status")
    tracking_number = payload.get("tracking_number")

    try:
        order.shipping_status = ShippingStatus(new_status)
    except Exception:
        raise HTTPException(400, "Invalid shipping status")

    if tracking_number:
        order.tracking_number = tracking_number

    # Auto-advance fulfillment flow
    if order.shipping_status == ShippingStatus.processing:
        pass
    elif order.shipping_status == ShippingStatus.shipped:
        pass
    elif order.shipping_status == ShippingStatus.delivered:
        pass

    db.commit()

    return {
        "message": "Shipping updated",
        "order_id": order.id,
        "shipping_status": order.shipping_status,
    }
