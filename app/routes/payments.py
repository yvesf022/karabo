from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from datetime import datetime
import uuid, os

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import Payment, PaymentStatus, PaymentMethod, Order

router = APIRouter(prefix="/payments", tags=["payments"])

UPLOAD_DIR = "uploads/payments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


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
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.user_id != user.id:
        raise HTTPException(404, "Order not found")

    if order.payment:
        raise HTTPException(400, "Payment already exists")

    ext = os.path.splitext(proof.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)

    with open(path, "wb") as f:
        f.write(proof.file.read())

    payment = Payment(
        order_id=order.id,
        method=PaymentMethod.bank_transfer,
        amount=order.total_amount,
        proof_url=f"/{UPLOAD_DIR}/{filename}",
        status=PaymentStatus.proof_submitted,
    )

    db.add(payment)
    db.commit()
    return {"message": "Payment proof submitted"}


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

    status = payload.get("status")
    if status not in (PaymentStatus.approved, PaymentStatus.rejected):
        raise HTTPException(400, "Invalid status")

    payment.status = status
    payment.reviewed_by_admin = True
    payment.reviewed_at = datetime.utcnow()

    db.commit()
    return {"message": "Payment reviewed"}
