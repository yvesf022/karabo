from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.models import (
    User,
    Payment,
    PaymentStatus,
    PaymentMethod,
    PaymentProof,
    PaymentStatusHistory,
    Order,
    OrderStatus,
    Notification,
)
from app.dependencies import get_current_user, require_admin
from app.uploads.service import handle_upload


router = APIRouter(prefix="/payments", tags=["payment-enhancements"])


# =====================================================
# HELPERS (local — mirrors payments.py helpers)
# =====================================================

def _record_status_history(
    db: Session,
    payment: Payment,
    old_status,
    new_status: PaymentStatus,
    changed_by_id=None,
    reason: Optional[str] = None,
):
    history = PaymentStatusHistory(
        payment_id=payment.id,
        old_status=old_status.value if old_status else None,
        new_status=new_status.value,
        changed_by=changed_by_id,
        reason=reason,
    )
    db.add(history)


def _notify_user(db: Session, user_id, title: str, message: str, link: str = None):
    try:
        notification = Notification(
            user_id=user_id,
            type="payment_status",
            title=title,
            message=message,
            link=link,
        )
        db.add(notification)
    except Exception:
        pass


# =====================================================
# Pydantic Schemas
# =====================================================

class CancelPaymentPayload(BaseModel):
    reason: str


class RetryPaymentPayload(BaseModel):
    method: Optional[str] = "bank_transfer"


class ForceStatusPayload(BaseModel):
    status: str
    reason: str


# =====================================================
# USER: RESUBMIT PAYMENT PROOF
# (After rejection, user can submit a new/corrected proof)
# =====================================================

@router.post("/{payment_id}/resubmit-proof", status_code=status.HTTP_200_OK)
def resubmit_payment_proof(
    payment_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Allows user to resubmit proof after rejection or while pending.
    Resets status to on_hold for admin re-review.
    """
    payment = (
        db.query(Payment)
        .join(Order, Payment.order_id == Order.id)
        .filter(Payment.id == payment_id, Order.user_id == user.id)
        .first()
    )
    if not payment:
        raise HTTPException(404, "Payment not found")

    if payment.status not in [PaymentStatus.rejected, PaymentStatus.pending, PaymentStatus.on_hold]:
        raise HTTPException(
            400,
            f"Cannot resubmit proof for payment in status '{payment.status.value}'. "
            "Only rejected, pending, or on_hold payments can be resubmitted.",
        )

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}
    if file.content_type not in allowed_types:
        raise HTTPException(400, "Only images (JPEG, PNG, WebP) and PDF files are allowed")

    # Max 10MB
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > 10 * 1024 * 1024:
        raise HTTPException(400, "File size must not exceed 10MB")

    proof_url = handle_upload(file=file, folder="payment_proofs", owner_id=str(user.id))

    # ✅ FIXED: flush before insert
    if payment.proof:
        db.delete(payment.proof)
        db.flush()

    proof = PaymentProof(payment_id=payment_id, file_url=proof_url)
    db.add(proof)

    old_status = payment.status
    payment.status = PaymentStatus.on_hold
    payment.admin_notes = None  # Clear rejection notes when resubmitting
    payment.reviewed_by = None
    payment.reviewed_at = None
    payment.updated_at = datetime.now(timezone.utc)

    _record_status_history(
        db, payment, old_status, PaymentStatus.on_hold,
        changed_by_id=user.id,
        reason="User resubmitted payment proof",
    )

    db.commit()

    return {
        "message": "Proof resubmitted successfully. Awaiting admin review.",
        "proof_url": proof_url,
        "payment_status": payment.status,
        "payment_id": str(payment.id),
    }


# =====================================================
# USER: CANCEL PAYMENT
# =====================================================

@router.post("/{payment_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_payment(
    payment_id: str,
    payload: CancelPaymentPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    User cancels a pending payment.
    Order is reset to pending so a new payment can be created.
    """
    payment = (
        db.query(Payment)
        .join(Order, Payment.order_id == Order.id)
        .options(joinedload(Payment.order))
        .filter(Payment.id == payment_id, Order.user_id == user.id)
        .first()
    )
    if not payment:
        raise HTTPException(404, "Payment not found")

    if payment.status not in [PaymentStatus.pending, PaymentStatus.on_hold]:
        raise HTTPException(
            400,
            f"Cannot cancel a payment in status '{payment.status.value}'. "
            "Only pending or on_hold payments can be cancelled.",
        )

    old_status = payment.status
    payment.status = PaymentStatus.rejected
    payment.admin_notes = (
        (payment.admin_notes + "\n" if payment.admin_notes else "")
        + f"[User cancelled: {payload.reason}]"
    )
    payment.updated_at = datetime.now(timezone.utc)

    # Reset order back to pending so user can start over
    if payment.order:
        payment.order.status = OrderStatus.pending

    _record_status_history(
        db, payment, old_status, PaymentStatus.rejected,
        changed_by_id=user.id,
        reason=f"User cancelled: {payload.reason}",
    )

    db.commit()

    return {
        "message": "Payment cancelled successfully. You can start a new payment.",
        "payment_id": str(payment.id),
        "order_id": str(payment.order_id),
    }


# =====================================================
# USER: RETRY PAYMENT
# (Creates a NEW payment attempt after rejection)
# =====================================================

@router.post("/{order_id}/retry", status_code=status.HTTP_201_CREATED)
def retry_payment(
    order_id: str,
    payload: RetryPaymentPayload = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Creates a new payment attempt for an order after the previous one was rejected.
    The rejected payment is kept for audit history.
    """
    import uuid as _uuid

    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == user.id,
    ).first()
    if not order:
        raise HTTPException(404, "Order not found")

    if order.status == OrderStatus.paid:
        raise HTTPException(400, "This order has already been paid.")

    if order.status == OrderStatus.cancelled:
        raise HTTPException(400, "Cannot retry payment for a cancelled order.")

    # Get the most recent payment
    latest_payment = (
        db.query(Payment)
        .filter(Payment.order_id == order.id)
        .order_by(Payment.created_at.desc())
        .first()
    )

    if latest_payment:
        if latest_payment.status in (PaymentStatus.pending, PaymentStatus.on_hold):
            raise HTTPException(
                400,
                f"A payment is already in progress (status: '{latest_payment.status.value}'). "
                "Please cancel it before retrying.",
            )
        if latest_payment.status == PaymentStatus.paid:
            raise HTTPException(400, "This order has already been paid.")
        # Only rejected payments can be retried

    # Determine method
    method_str = (payload.method if payload else None) or "bank_transfer"
    try:
        method = PaymentMethod(method_str)
    except ValueError:
        raise HTTPException(400, f"Invalid payment method: '{method_str}'")

    ref = f"PAY-{str(_uuid.uuid4()).upper()[:8]}"

    new_payment = Payment(
        order_id=order.id,
        amount=order.total_amount,
        method=method,
        status=PaymentStatus.pending,
        reference_number=ref,
    )
    db.add(new_payment)

    _record_status_history(
        db, new_payment, None, PaymentStatus.pending,
        changed_by_id=user.id,
        reason="User initiated payment retry",
    )

    db.commit()
    db.refresh(new_payment)

    return {
        "message": "New payment attempt created. Please upload your proof of payment.",
        "payment_id": str(new_payment.id),
        "order_id": str(order_id),
        "amount": new_payment.amount,
        "method": new_payment.method,
        "reference_number": new_payment.reference_number,
        "status": new_payment.status,
    }


# =====================================================
# USER: GET PAYMENT STATUS HISTORY
# =====================================================

@router.get("/{payment_id}/status-history", status_code=status.HTTP_200_OK)
def get_payment_status_history(
    payment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full audit trail of payment status changes."""
    payment = (
        db.query(Payment)
        .join(Order, Payment.order_id == Order.id)
        .filter(Payment.id == payment_id, Order.user_id == user.id)
        .first()
    )
    if not payment:
        raise HTTPException(404, "Payment not found")

    history = (
        db.query(PaymentStatusHistory)
        .filter(PaymentStatusHistory.payment_id == payment_id)
        .order_by(PaymentStatusHistory.created_at.asc())
        .all()
    )

    return {
        "payment_id": payment_id,
        "current_status": payment.status,
        "history": [
            {
                "old_status": h.old_status,
                "new_status": h.new_status,
                "reason": h.reason,
                "created_at": h.created_at,
            }
            for h in history
        ],
    }


# =====================================================
# USER: GET ALL PAYMENT ATTEMPTS FOR AN ORDER
# (Useful on the payment page to show all past attempts)
# =====================================================

@router.get("/order/{order_id}/attempts")
def get_payment_attempts(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Returns all payment attempts for an order, most recent first."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == user.id,
    ).first()
    if not order:
        raise HTTPException(404, "Order not found")

    payments = (
        db.query(Payment)
        .options(joinedload(Payment.proof))
        .filter(Payment.order_id == order_id)
        .order_by(Payment.created_at.desc())
        .all()
    )

    return {
        "order_id": order_id,
        "order_status": order.status,
        "total_attempts": len(payments),
        "attempts": [
            {
                "id": str(p.id),
                "amount": p.amount,
                "status": p.status,
                "method": p.method,
                "reference_number": p.reference_number,
                "has_proof": p.proof is not None,
                "proof_url": p.proof.file_url if p.proof else None,
                "admin_notes": p.admin_notes,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in payments
        ],
    }


# =====================================================
# ADMIN: HARD DELETE PAYMENT
# =====================================================

@router.delete("/admin/{payment_id}", dependencies=[Depends(require_admin)])
def hard_delete_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Permanently delete a payment record. Use with extreme caution."""
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(404, "Payment not found")

    if payment.status == PaymentStatus.paid:
        raise HTTPException(
            400,
            "Cannot delete a confirmed payment. Use force status override instead.",
        )

    db.delete(payment)
    db.commit()
    return {"message": "Payment permanently deleted", "payment_id": payment_id}


# =====================================================
# ADMIN: FORCE STATUS OVERRIDE
# =====================================================

@router.patch("/admin/{payment_id}/status", dependencies=[Depends(require_admin)])
def force_payment_status(
    payment_id: str,
    payload: ForceStatusPayload,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """
    Admin force-override of payment status.
    Full audit trail recorded. Syncs order status accordingly.
    """
    valid_statuses = [s.value for s in PaymentStatus]
    if payload.status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid_statuses}")

    payment = (
        db.query(Payment)
        .options(joinedload(Payment.order))
        .filter(Payment.id == payment_id)
        .first()
    )
    if not payment:
        raise HTTPException(404, "Payment not found")

    old_status = payment.status
    new_status = PaymentStatus(payload.status)

    payment.status = new_status
    payment.reviewed_by = admin.id
    payment.reviewed_at = datetime.now(timezone.utc)
    payment.updated_at = datetime.now(timezone.utc)

    # Sync order
    if payment.order:
        if new_status == PaymentStatus.paid:
            payment.order.status = OrderStatus.paid
        elif new_status in (PaymentStatus.rejected, PaymentStatus.pending):
            payment.order.status = OrderStatus.pending

    _record_status_history(
        db, payment, old_status, new_status,
        changed_by_id=admin.id,
        reason=f"[ADMIN FORCE OVERRIDE] {payload.reason}",
    )

    # Notify user
    if payment.order:
        _notify_user(
            db, payment.order.user_id,
            title="Payment Status Updated",
            message=f"Your payment status has been updated to: {new_status.value}.",
            link=f"/account/orders/{payment.order_id}",
        )

    db.commit()

    return {
        "message": f"Payment status force-updated to '{payload.status}'",
        "payment_id": payment_id,
        "old_status": old_status.value,
        "new_status": new_status.value,
        "reason": payload.reason,
    }


# =====================================================
# ADMIN: GET PAYMENT HISTORY (Admin view, full detail)
# =====================================================

@router.get("/admin/{payment_id}/history", dependencies=[Depends(require_admin)])
def get_payment_history_admin(
    payment_id: str,
    db: Session = Depends(get_db),
):
    """Full audit history for a payment — for admin view."""
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(404, "Payment not found")

    history = (
        db.query(PaymentStatusHistory)
        .filter(PaymentStatusHistory.payment_id == payment_id)
        .order_by(PaymentStatusHistory.created_at.asc())
        .all()
    )

    return {
        "payment_id": payment_id,
        "current_status": payment.status,
        "history": [
            {
                "id": str(h.id),
                "old_status": h.old_status,
                "new_status": h.new_status,
                "changed_by": str(h.changed_by) if h.changed_by else None,
                "reason": h.reason,
                "created_at": h.created_at,
            }
            for h in history
        ],
    }