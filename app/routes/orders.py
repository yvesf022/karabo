from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import (
    Order,
    OrderStatus,
    ShippingStatus,
    Payment,
    User,
)

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
        shipping_address=payload.get("shipping_address"),
        notes=payload.get("notes"),
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
            "shipping_address": o.shipping_address,
            "notes": o.notes,
            "created_at": o.created_at,
            "updated_at": o.updated_at,
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
    status_filter: str = None,
):
    query = db.query(Order).order_by(Order.created_at.desc())

    if status_filter:
        try:
            query = query.filter(Order.status == OrderStatus(status_filter))
        except ValueError:
            pass  # ignore invalid filter, return all

    orders = query.all()

    return [
        {
            "id": str(o.id),
            "user_id": str(o.user_id),
            "total_amount": o.total_amount,
            "status": o.status,
            "shipping_status": o.shipping_status,
            "shipping_address": o.shipping_address,
            "notes": o.notes,
            "created_at": o.created_at,
            "updated_at": o.updated_at,
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


# =====================================================
# ✅ NEW — USER: GET SINGLE ORDER DETAIL
# GET /api/orders/{order_id}
# =====================================================
@router.get("/{order_id}")
def get_my_order_detail(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = (
        db.query(Order)
        .options(joinedload(Order.payments).joinedload(Payment.proof))
        .filter(Order.id == order_id, Order.user_id == user.id)
        .first()
    )

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "id": str(order.id),
        "user_id": str(order.user_id),
        "total_amount": order.total_amount,
        "status": order.status,
        "shipping_status": order.shipping_status,
        "shipping_address": order.shipping_address,
        "notes": order.notes,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "payments": [
            {
                "id": str(p.id),
                "amount": p.amount,
                "status": p.status,
                "method": p.method,
                "proof": (
                    {
                        "id": str(p.proof.id),
                        "file_url": p.proof.file_url,
                        "uploaded_at": p.proof.uploaded_at,
                    }
                    if p.proof
                    else None
                ),
                "reviewed_at": p.reviewed_at,
                "created_at": p.created_at,
            }
            for p in order.payments
        ],
    }


# =====================================================
# ✅ NEW — ADMIN: GET SINGLE ORDER DETAIL
# GET /api/orders/admin/{order_id}
# =====================================================
@router.get("/admin/{order_id}")
def admin_get_order_detail(
    order_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    order = (
        db.query(Order)
        .options(joinedload(Order.payments).joinedload(Payment.proof))
        .filter(Order.id == order_id)
        .first()
    )

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "id": str(order.id),
        "user_id": str(order.user_id),
        "total_amount": order.total_amount,
        "status": order.status,
        "shipping_status": order.shipping_status,
        "shipping_address": order.shipping_address,
        "notes": order.notes,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "payments": [
            {
                "id": str(p.id),
                "amount": p.amount,
                "status": p.status,
                "method": p.method,
                "proof": (
                    {
                        "id": str(p.proof.id),
                        "file_url": p.proof.file_url,
                        "uploaded_at": p.proof.uploaded_at,
                    }
                    if p.proof
                    else None
                ),
                "admin_notes": p.admin_notes,
                "reviewed_by": str(p.reviewed_by) if p.reviewed_by else None,
                "reviewed_at": p.reviewed_at,
                "created_at": p.created_at,
            }
            for p in order.payments
        ],
    }