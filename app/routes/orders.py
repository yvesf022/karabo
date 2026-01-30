from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import Order, ShippingStatus

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
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return {"order_id": order.id}


# =============================
# USER: MY ORDERS
# =============================
@router.get("/my")
def my_orders(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    orders = db.query(Order).filter(Order.user_id == user.id).all()

    return [
        {
            "id": o.id,
            "total_amount": o.total_amount,
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

    order.shipping_status = ShippingStatus(payload.get("status"))
    order.tracking_number = payload.get("tracking_number")

    db.commit()
    return {"message": "Order updated"}
