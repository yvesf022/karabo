import uuid
import os
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.models import Order, Payment, OrderStatus
from app.dependencies import get_current_user, require_admin
from app.models import User

router = APIRouter(prefix="/orders", tags=["orders"])

UPLOAD_DIR = "uploads/payments"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# -------------------------------------------------
# CREATE ORDER (NO PAYMENT YET)
# -------------------------------------------------
@router.post("")
def create_order(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = payload.get("items")
    delivery_address = payload.get("delivery_address")
    total_amount = payload.get("total_amount")

    if not items or not delivery_address or not total_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing order data",
        )

    order_ref = f"ORD-{uuid.uuid4().hex[:10].upper()}"

    order = Order(
        order_reference=order_ref,
        customer_id=user.id,
        items=items,
        delivery_address=delivery_address,
        total_amount=total_amount,
        status=OrderStatus.awaiting_payment,
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "order_id": str(order.id),
        "order_reference": order.order_reference,
        "status": order.status.value,
        "message": "Order created. Awaiting payment.",
    }


# -------------------------------------------------
# SUBMIT PAYMENT PROOF (MULTIPLE ALLOWED)
# -------------------------------------------------
@router.post("/{order_id}/payments")
def submit_payment_proof(
    order_id: str,
    amount: float,
    method: str,
    proof: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")

    if order.status == OrderStatus.cancelled:
        raise HTTPException(status_code=400, detail="Order cancelled")

    # Save proof file
    ext = os.path.splitext(proof.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as f:
        f.write(proof.file.read())

    payment = Payment(
        order_id=order.id,
        user_id=user.id,
        amount=amount,
        method=method,
        proof_file_url=file_path,
        status="submitted",
    )

    order.status = OrderStatus.payment_submitted

    db.add(payment)
    db.commit()

    return {
        "message": "Payment proof submitted. Awaiting admin verification.",
    }


# -------------------------------------------------
# USER: VIEW MY ORDERS
# -------------------------------------------------
@router.get("/my")
def get_my_orders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    orders = db.query(Order).filter(Order.customer_id == user.id).all()

    return [
        {
            "id": str(o.id),
            "reference": o.order_reference,
            "status": o.status.value,
            "total": float(o.total_amount),
            "created_at": o.created_at,
        }
        for o in orders
    ]


# -------------------------------------------------
# ADMIN: VIEW PENDING PAYMENTS
# -------------------------------------------------
@router.get("/admin/pending-payments")
def get_pending_payments(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    payments = db.query(Payment).filter(Payment.status == "submitted").all()

    return [
        {
            "payment_id": str(p.id),
            "order_id": str(p.order_id),
            "amount": float(p.amount),
            "method": p.method,
            "proof": p.proof_file_url,
            "created_at": p.created_at,
        }
        for p in payments
    ]


# -------------------------------------------------
# ADMIN: VERIFY / REJECT PAYMENT
# -------------------------------------------------
@router.post("/admin/payments/{payment_id}")
def review_payment(
    payment_id: str,
    action: str,  # verify | reject
    note: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    order = db.query(Order).filter(Order.id == payment.order_id).first()

    if action == "verify":
        payment.status = "verified"
        order.status = OrderStatus.payment_verified
    elif action == "reject":
        payment.status = "rejected"
        order.status = OrderStatus.payment_rejected
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    payment.admin_note = note

    db.commit()

    return {
        "message": f"Payment {action}ed successfully",
    }
from app.models import PaymentSetting

# -------------------------------------------------
# USER: GET PAYMENT INSTRUCTIONS
# -------------------------------------------------
@router.get("/{order_id}/payment-instructions")
def get_payment_instructions(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")

    setting = (
        db.query(PaymentSetting)
        .filter(
            PaymentSetting.method == "bank_transfer",
            PaymentSetting.is_active == True,
        )
        .first()
    )

    if not setting:
        raise HTTPException(
            status_code=503,
            detail="Payment instructions not configured",
        )

    return {
        "order_reference": order.order_reference,
        "amount": float(order.total_amount),
        "currency": order.currency,
        "bank_details": {
            "bank_name": setting.provider_name,
            "account_name": setting.account_name,
            "account_number": setting.account_number,
            "reference": order.order_reference,
            "instructions": setting.instructions,
        },
    }

