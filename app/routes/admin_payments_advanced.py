from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from app.database import get_db
from app.models import User, Payment, PaymentStatus, PaymentStatusHistory
from app.dependencies import require_admin

router = APIRouter(prefix="/payments/admin", tags=["admin-payments-advanced"])

class StatusOverridePayload(BaseModel):
    status: str
    reason: str

@router.delete("/{payment_id}", status_code=status.HTTP_200_OK)
def hard_delete_payment(payment_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(404, "Payment not found")
    db.delete(payment)
    db.commit()
    return {"message": "Payment permanently deleted"}

@router.patch("/{payment_id}/status", status_code=status.HTTP_200_OK)
def force_payment_status_override(payment_id: str, payload: StatusOverridePayload, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(404, "Payment not found")
    old_status = payment.status
    try:
        payment.status = PaymentStatus(payload.status)
    except ValueError:
        raise HTTPException(400, "Invalid status")
    payment.reviewed_by = admin.id
    payment.reviewed_at = datetime.utcnow()
    if payment.admin_notes:
        payment.admin_notes += f"\n[Force override by {admin.email}: {payload.reason}]"
    else:
        payment.admin_notes = f"[Force override by {admin.email}: {payload.reason}]"
    history = PaymentStatusHistory(payment_id=payment_id, old_status=old_status, new_status=payload.status, changed_by=admin.id, reason=payload.reason)
    db.add(history)
    db.commit()
    return {"message": "Payment status overridden", "new_status": payment.status}

@router.get("/{payment_id}/history", status_code=status.HTTP_200_OK)
def get_payment_history(payment_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    history = db.query(PaymentStatusHistory).filter(PaymentStatusHistory.payment_id == payment_id).order_by(PaymentStatusHistory.created_at.desc()).all()
    return [{"id": str(h.id), "old_status": h.old_status, "new_status": h.new_status, "changed_by": str(h.changed_by) if h.changed_by else None, "reason": h.reason, "created_at": h.created_at} for h in history]
