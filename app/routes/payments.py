from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from datetime import datetime
import uuid, os

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import (
    Payment,
    PaymentStatus,
    PaymentMethod,
    Order,
    OrderStatus,
)

router = APIRouter(prefix="/payments", tags=["payments"])

UPLOAD_DIR = "uploads/payments"
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_FILE_SIZE_MB = 5


# =============================
# USER: SUBMIT PAYMENT PROOF
# =============================
@router.post("/{order_id}/proof")
def submit_payment_proof(
    order_id: str,
    proof: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    order = (
        db.query(Order)
        .filter(Order.id == order_id, Order.user_id == user.id)
        .first()
    )

    if not order:
        raise HTTPException(404, "Order not found")

    # 🔒 Order must be awaiting payment
    if order.order_status != OrderStatus.awaiting_payment:
        raise HTTPException(
            400,
            f"Cannot submit payment for order in state '{order.order_status}'",
        )

    # 🔒 One payment per order
    if order.payment:
        raise HTTPException(400, "Payment already submitted for this order")

    # 🔒 File validation
    ext = os.path.splitext(proof.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Invalid file type")

    content = proof.file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(400, "File too large (max 5MB)")

    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)

    with open(path, "wb") as f:
        f.write(content)

    payment = Payment(
        order_id=order.id,
        method=PaymentMethod.bank_transfer,
        amount=order.total_amount,
        proof_url=f"/{UPLOAD_DIR}/{filename}",
        status=PaymentStatus.proof_submitted,
    )

    # 🔑 ORDER STATE TRANSITION
    order.order_status = OrderStatus.payment_under_review

    db.add(payment)
    db.commit()

    return {
        "message": "Payment proof submitted",
        "order_id": order.id,
        "order_status": order.order_status,
        "payment_status": payment.status,
    }


# =============================
# ADMIN: LIST PAYMENTS
# =============================
@router.get("/admin")
def admin_list_payments(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    payments = db.query(Payment).order_by(Payment.created_at.desc()).all()

    return [
        {
            "id": p.id,
            "order_id": p.order_id,
            "amount": p.amount,
            "status": p.status,
            "created_at": p.created_at,
        }
        for p in payments
    ]


# =============================
# ADMIN: REVIEW PAYMENT
# =============================
@router.post("/admin/{payment_id}/review")
def review_payment(
    payment_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(404, "Payment not found")

    order = payment.order
    if not order:
        raise HTTPException(500, "Payment has no associated order")

    if payment.status != PaymentStatus.proof_submitted:
        raise HTTPException(
            400,
            f"Payment already reviewed (status: {payment.status})",
        )

    new_status = payload.get("status")

    if new_status not in (
        PaymentStatus.approved,
        PaymentStatus.rejected,
    ):
        raise HTTPException(400, "Invalid payment status")

    # =============================
    # APPROVE PAYMENT
    # =============================
    if new_status == PaymentStatus.approved:
        payment.status = PaymentStatus.approved
        order.order_status = OrderStatus.paid

    # =============================
    # REJECT PAYMENT
    # =============================
    elif new_status == PaymentStatus.rejected:
        payment.status = PaymentStatus.rejected
        order.order_status = OrderStatus.cancelled

    payment.reviewed_by_admin = True
    payment.reviewed_at = datetime.utcnow()

    db.commit()

    return {
        "message": "Payment reviewed",
        "order_id": order.id,
        "order_status": order.order_status,
        "payment_status": payment.status,
    }
