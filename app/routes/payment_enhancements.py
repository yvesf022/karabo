from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
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
# HELPERS
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
# SCHEMAS
# =====================================================

class CancelPaymentPayload(BaseModel):
    reason: str


class RetryPaymentPayload(BaseModel):
    method: Optional[str] = "bank_transfer"


class ForceStatusPayload(BaseModel):
    status: str
    reason: str


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
        "current_status": payment.status.value,  # FIXED: enum serialization
        "history": [
            {
                "old_status": h.old_status,
                "new_status": h.new_status,
                "reason": h.reason,
                "created_at": h.created_at.isoformat() if h.created_at else None,  # FIXED: datetime serialization
            }
            for h in history
        ],
    }