import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, Payment, OrderStatus
from app.dependencies import get_current_user, require_admin
from app.models import User

router = APIRouter(prefix="/orders", tags=["orders"])

UPLOAD_DIR = "uploads/payments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# -----------------------------
# USER: CREATE ORDER
# -----------------------------
@router.post("")
def create_order(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = payload.get("items")
    total_amount = payload.get("total_amount")

    if not items or not total_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing order data",
        )

    order = Order(
        user_id=user.id,
        items=items,
        total_amount=total_amount,
        shipping_status=OrderStatus.created,
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "order_id": order.id,
        "status": order.shipping_status.value,
    }


# -----------------------------
# USER: UPLOAD PAYMENT PROOF
# -----------------------------
@router.post("/{order_id}/payment-proof")
def submit_payment_proof(
    order_id: str,
    proof: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")

    ext = os.path.splitext(proof.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(proof.file.read())

    payment = Payment(
        order_id=order.id,
        proof_url=f"/{UPLOAD_DIR}/{filename}",
        approved=False,
    )

    order.shipping_status = OrderStatus.pending

    db.add(payment)
    db.commit()

    return {"message": "Payment proof submitted"}


# -----------------------------
# USER: MY ORDERS
# -----------------------------
@router.get("/my")
def my_orders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    orders = db.query(Order).filter(Order.user_id == user.id).all()

    return [
        {
            "id": o.id,
            "total": o.total_amount,
            "status": o.shipping_status.value,
            "created_at": o.created_at,
        }
        for o in orders
    ]


# -----------------------------
# ADMIN: ALL ORDERS
# -----------------------------
@router.get("/admin")
def admin_orders(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    orders = db.query(Order).all()
    return [
        {
            "id": o.id,
            "user_id": o.user_id,
            "total": o.total_amount,
            "status": o.shipping_status.value,
        }
        for o in orders
    ]


# -----------------------------
# ADMIN: UPDATE SHIPPING STATUS
# -----------------------------
@router.post("/admin/{order_id}/status")
def update_shipping_status(
    order_id: str,
    status_value: OrderStatus,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.shipping_status = status_value
    db.commit()

    return {
        "order_id": order.id,
        "new_status": order.shipping_status.value,
    }
