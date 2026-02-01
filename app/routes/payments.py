from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import uuid, os

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import (
    Payment,
    PaymentProof,
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


# =====================================================
# USER: CREATE PAYMENT (INITIAL RECORD)
# =====================================================
@router.post("/{order_id}")
def create_payment(
    order_id: str,
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

    if order.status != OrderStatus.pending:
        raise HTTPException(
            400,
            f"Cannot pay for order in status '{order.status}'",
        )

    existing = db.query(Payment).filter(Payment.order_id == order.id).first()
    if existing:
        raise HTTPException(400, "Payment already exists for this order")

    payment = Payment(
        order_id=order.id,
        amount=order.total_amount,
        method=PaymentMethod.bank_transfer,
        status=PaymentStatus.pending,
    )

    db.add(payment)
    db.commit()
    db.refresh(payment)

    return {
        "payment_id": str(payment.id),
        "order_id": str(order.id),
        "amount": payment.amount,
        "status": payment.status,
    }


# =====================================================
# USER: UPLOAD PAYMENT PROOF
# =====================================================
@router.post("/{payment_id}/proof")
def upload_payment_proof(
    payment_id: str,
    proof: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    payment = (
        db.query(Payment)
        .join(Order, Payment.order_id == Order.id)
        .filter(Payment.id == payment_id, Order.user_id == user.id)
        .first()
    )
    if not payment:
        raise HTTPException(404, "Payment not found")

    if payment.status != PaymentStatus.pending:
        raise HTTPException(
            400,
            f"Cannot upload proof for payment in status '{payment.status}'",
        )

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

    proof_record = PaymentProof(
        payment_id=payment.id,
        file_url=f"/uploads/payments/{filename}",
    )

    db.add(proof_record)
    db.commit()

    return {
        "message": "Payment proof uploaded",
        "proof_url": proof_record.file_url,
    }


# =====================================================
# ADMIN: LIST PAYMENTS (WITH PROOFS)
# =====================================================
@router.get("/admin", dependencies=[Depends(require_admin)])
def admin_list_payments(db: Session = Depends(get_db)):
    payments = db.query(Payment).order_by(Payment.created_at.desc()).all()

    return [
        {
            "id": str(p.id),
            "order_id": str(p.order_id),
            "amount": p.amount,
            "status": p.status,
            "method": p.method,
            "proofs": [
                {
                    "id": str(pr.id),
                    "file_url": pr.file_url,
                    "uploaded_at": pr.uploaded_at,
                }
                for pr in db.query(PaymentProof)
                .filter(PaymentProof.payment_id == p.id)
                .all()
            ],
            "created_at": p.created_at,
        }
        for p in payments
    ]


# =====================================================
# ADMIN: REVIEW PAYMENT
# =====================================================
@router.post("/admin/{payment_id}")
def review_payment(
    payment_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(404, "Payment not found")

    order = db.query(Order).filter(Order.id == payment.order_id).first()
    if not order:
        raise HTTPException(500, "Order not found")

    if payment.status != PaymentStatus.pending:
        raise HTTPException(
            400,
            f"Payment already reviewed (status: {payment.status})",
        )

    new_status = payload.get("status")
    if new_status not in (PaymentStatus.paid, PaymentStatus.rejected):
        raise HTTPException(400, "Invalid payment status")

    if new_status == PaymentStatus.paid:
        payment.status = PaymentStatus.paid
        order.status = OrderStatus.paid
    else:
        payment.status = PaymentStatus.rejected
        order.status = OrderStatus.cancelled

    db.commit()

    return {
        "payment_id": str(payment.id),
        "payment_status": payment.status,
        "order_id": str(order.id),
        "order_status": order.status,
    }
