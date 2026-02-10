from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import (
    Order,
    OrderStatus,
    ShippingStatus,
    User,
)

# ✅ FIXED: Changed prefix from /api/orders to /orders (since /api is added in main.py)
router = APIRouter(prefix="/orders", tags=["orders"])


# =====================================================
# USER: CREATE ORDER
# =====================================================
@router.post("")
def create_order(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    total = payload.get("total_amount")

    if not total:
        raise HTTPException(400, "Invalid order data")

    order = Order(
        user_id=user.id,
        total_amount=total,
        status=OrderStatus.pending,
        shipping_status=ShippingStatus.pending,
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "order_id": str(order.id),
        "status": order.status,
    }


# =====================================================
# USER: MY ORDERS
# =====================================================
@router.get("/my")
def my_orders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    orders = (
        db.query(Order)
        .filter(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .all()
    )

    return [
        {
            "id": str(o.id),
            "total_amount": o.total_amount,
            "status": o.status,
            "shipping_status": o.shipping_status,
            "created_at": o.created_at,
        }
        for o in orders
    ]


# =====================================================
# ADMIN: LIST ALL ORDERS
# =====================================================
@router.get("/admin")
def admin_orders(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    orders = db.query(Order).order_by(Order.created_at.desc()).all()

    return [
        {
            "id": str(o.id),
            "total_amount": o.total_amount,
            "status": o.status,
            "shipping_status": o.shipping_status,
            "created_at": o.created_at,
        }
        for o in orders
    ]


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
        raise HTTPException(
            400,
            "Order cannot be shipped before payment is approved",
        )

    new_status = payload.get("status")

    try:
        order.shipping_status = ShippingStatus(new_status)
    except Exception:
        raise HTTPException(400, "Invalid shipping status")

    db.commit()

    return {
        "message": "Shipping updated",
        "order_id": str(order.id),
        "shipping_status": order.shipping_status,
    }
