from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session, joinedload

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
from app.uploads.service import handle_upload

# ✅ FIXED: Changed prefix from /payments to /api/payments
router = APIRouter(prefix="/api/payments", tags=["payments"])


# =====================================================
# USER: CREATE PAYMENT
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
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != OrderStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pay for order in status '{order.status}'",
        )

    existing = (
        db.query(Payment)
        .filter(Payment.order_id == order.id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Payment already exists for this order",
        )

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
# USER: UPLOAD PAYMENT PROOF (CENTRALIZED)
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
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status != PaymentStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot upload proof for payment in status '{payment.status}'",
        )

    proof_url = handle_upload(
        file=proof,
        folder="payments",
        owner_id=str(payment.id),
    )

    proof_record = PaymentProof(
        payment_id=payment.id,
        file_url=proof_url,
    )

    db.add(proof_record)
    db.commit()
    db.refresh(proof_record)

    return {
        "message": "Payment proof uploaded",
        "proof_url": proof_record.file_url,
    }


# =====================================================
# ADMIN: LIST PAYMENTS
# =====================================================
@router.get("/admin", dependencies=[Depends(require_admin)])
def admin_list_payments(db: Session = Depends(get_db)):
    payments = (
        db.query(Payment)
        .options(joinedload(Payment.proof))
        .order_by(Payment.created_at.desc())
        .all()
    )

    return [
        {
            "id": str(p.id),
            "order_id": str(p.order_id),
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
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    order = (
        db.query(Order)
        .filter(Order.id == payment.order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=500, detail="Order not found")

    if payment.status != PaymentStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Payment already reviewed (status: {payment.status})",
        )

    new_status = payload.get("status")
    if new_status not in (PaymentStatus.paid.value, PaymentStatus.rejected.value):
        raise HTTPException(
            status_code=400,
            detail="Invalid payment status",
        )

    if new_status == PaymentStatus.paid.value:
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
