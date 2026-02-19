from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel
import uuid

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import (
    Payment,
    PaymentProof,
    PaymentStatus,
    PaymentMethod,
    PaymentStatusHistory,
    Order,
    OrderStatus,
    BankSettings,
    Notification,
    User,
)
from app.uploads.service import handle_upload


router = APIRouter(prefix="/payments", tags=["payments"])


# =====================================================
# HELPERS
# =====================================================

def _record_status_history(
    db: Session,
    payment: Payment,
    old_status: PaymentStatus,
    new_status: PaymentStatus,
    changed_by_id=None,
    reason: Optional[str] = None,
):
    """Always record every status transition for full audit trail."""
    history = PaymentStatusHistory(
        payment_id=payment.id,
        old_status=old_status.value if old_status else None,
        new_status=new_status.value,
        changed_by=changed_by_id,
        reason=reason,
    )
    db.add(history)


def _notify_user(db: Session, user_id, title: str, message: str, link: str = None):
    """Fire-and-forget in-app notification."""
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
        pass  # Never let notification failure break payment flow


def _serialize_payment(p: Payment, include_order: bool = False) -> dict:
    data = {
        "id": str(p.id),
        "order_id": str(p.order_id),
        "amount": p.amount,
        "status": p.status,
        "method": p.method,
        "reference_number": p.reference_number,
        "proof": (
            {
                "id": str(p.proof.id),
                "file_url": p.proof.file_url,
                "uploaded_at": p.proof.uploaded_at,
            }
            if p.proof else None
        ),
        "admin_notes": p.admin_notes,
        "reviewed_by": str(p.reviewed_by) if p.reviewed_by else None,
        "reviewed_at": p.reviewed_at,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "expires_at": p.expires_at,
    }
    if include_order and p.order:
        data["order"] = {
            "id": str(p.order.id),
            "status": p.order.status,
            "total_amount": p.order.total_amount,
        }
    return data


# =====================================================
# Pydantic Schemas
# =====================================================

class BankSettingsCreate(BaseModel):
    bank_name: str
    account_name: str
    account_number: str
    branch: Optional[str] = None
    swift_code: Optional[str] = None
    mobile_money_provider: Optional[str] = None
    mobile_money_number: Optional[str] = None
    mobile_money_name: Optional[str] = None
    qr_code_url: Optional[str] = None
    instructions: Optional[str] = None
    is_active: bool = True
    is_primary: bool = False


class BankSettingsUpdate(BaseModel):
    bank_name: Optional[str] = None
    account_name: Optional[str] = None
    account_number: Optional[str] = None
    branch: Optional[str] = None
    swift_code: Optional[str] = None
    mobile_money_provider: Optional[str] = None
    mobile_money_number: Optional[str] = None
    mobile_money_name: Optional[str] = None
    qr_code_url: Optional[str] = None
    instructions: Optional[str] = None
    is_active: Optional[bool] = None
    is_primary: Optional[bool] = None


class PaymentReviewPayload(BaseModel):
    status: str  # "paid" | "rejected"
    admin_notes: Optional[str] = None


class CreatePaymentPayload(BaseModel):
    method: Optional[str] = "bank_transfer"  # bank_transfer | mobile_money


class UpdatePaymentMethodPayload(BaseModel):
    method: str  # bank_transfer | mobile_money


# =====================================================
# PUBLIC: GET BANK DETAILS FOR PAYMENT
# =====================================================

@router.get("/bank-details")
def get_bank_details(db: Session = Depends(get_db)):
    """
    Returns all active bank/mobile money payment options.
    Sorted: primary first, then by name.
    """
    banks = (
        db.query(BankSettings)
        .filter(BankSettings.is_active == True)
        .order_by(BankSettings.is_primary.desc(), BankSettings.bank_name)
        .all()
    )
    if not banks:
        raise HTTPException(
            status_code=404,
            detail="No payment details configured. Please contact support.",
        )
    return [
        {
            "id": str(b.id),
            "bank_name": b.bank_name,
            "account_name": b.account_name,
            "account_number": b.account_number,
            "branch": b.branch,
            "swift_code": b.swift_code,
            "mobile_money_provider": b.mobile_money_provider,
            "mobile_money_number": b.mobile_money_number,
            "mobile_money_name": b.mobile_money_name,
            "qr_code_url": b.qr_code_url,
            "instructions": b.instructions,
            "is_primary": b.is_primary,
        }
        for b in banks
    ]


# =====================================================
# USER: GET MY PAYMENTS (paginated)
# =====================================================

@router.get("/my")
def get_my_payments(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = (
        db.query(Payment)
        .join(Order, Payment.order_id == Order.id)
        .options(joinedload(Payment.proof))
        .filter(Order.user_id == user.id)
    )
    if status_filter:
        try:
            query = query.filter(Payment.status == PaymentStatus(status_filter))
        except ValueError:
            raise HTTPException(400, f"Invalid status filter: '{status_filter}'")

    total = query.count()
    payments = (
        query.order_by(Payment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "results": [_serialize_payment(p) for p in payments],
    }


# =====================================================
# ADMIN: LIST PAYMENTS (paginated + filterable)
# =====================================================

@router.get("/admin", dependencies=[Depends(require_admin)])
def admin_list_payments(
    db: Session = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status"),
    method_filter: Optional[str] = Query(None, alias="method"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search by order ID or payment ID"),
):
    query = (
        db.query(Payment)
        .options(joinedload(Payment.proof), joinedload(Payment.order))
    )
    if status_filter:
        try:
            query = query.filter(Payment.status == PaymentStatus(status_filter))
        except ValueError:
            raise HTTPException(400, f"Invalid status: '{status_filter}'")
    if method_filter:
        try:
            query = query.filter(Payment.method == PaymentMethod(method_filter))
        except ValueError:
            raise HTTPException(400, f"Invalid method: '{method_filter}'")
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            Payment.id.cast(db.bind.dialect.name == "postgresql" and
                            __import__("sqlalchemy").String or
                            __import__("sqlalchemy").String).like(search_term)
        )

    total = query.count()
    payments = (
        query.order_by(Payment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Summary stats for admin dashboard
    stats = db.query(
        Payment.status,
        func.count(Payment.id).label("count"),
        func.sum(Payment.amount).label("total_amount"),
    ).group_by(Payment.status).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "stats": {
            s.status.value: {"count": s.count, "total_amount": s.total_amount or 0}
            for s in stats
        },
        "results": [_serialize_payment(p, include_order=True) for p in payments],
    }


# =====================================================
# ADMIN: PAYMENT STATS SUMMARY
# =====================================================

@router.get("/admin/stats", dependencies=[Depends(require_admin)])
def admin_payment_stats(
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Revenue and volume stats for admin dashboard."""
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stats = db.query(
        Payment.status,
        func.count(Payment.id).label("count"),
        func.sum(Payment.amount).label("total"),
    ).filter(Payment.created_at >= since).group_by(Payment.status).all()

    total_revenue = db.query(func.sum(Payment.amount)).filter(
        Payment.status == PaymentStatus.paid,
        Payment.created_at >= since,
    ).scalar() or 0

    pending_count = db.query(func.count(Payment.id)).filter(
        Payment.status.in_([PaymentStatus.pending, PaymentStatus.on_hold])
    ).scalar() or 0

    return {
        "period_days": days,
        "total_revenue": total_revenue,
        "pending_review_count": pending_count,
        "by_status": {
            s.status.value: {"count": s.count, "total": s.total or 0}
            for s in stats
        },
    }


# =====================================================
# ADMIN: GET BANK SETTINGS
# =====================================================

@router.get("/admin/bank-settings", dependencies=[Depends(require_admin)])
def get_bank_settings(db: Session = Depends(get_db)):
    settings = db.query(BankSettings).order_by(BankSettings.is_primary.desc()).all()
    return [
        {
            "id": str(s.id),
            "bank_name": s.bank_name,
            "account_name": s.account_name,
            "account_number": s.account_number,
            "branch": s.branch,
            "swift_code": s.swift_code,
            "mobile_money_provider": s.mobile_money_provider,
            "mobile_money_number": s.mobile_money_number,
            "mobile_money_name": s.mobile_money_name,
            "qr_code_url": s.qr_code_url,
            "instructions": s.instructions,
            "is_active": s.is_active,
            "is_primary": s.is_primary,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
        for s in settings
    ]


# =====================================================
# ADMIN: CREATE BANK SETTINGS
# =====================================================

@router.post("/admin/bank-settings", dependencies=[Depends(require_admin)], status_code=201)
def create_bank_settings(payload: BankSettingsCreate, db: Session = Depends(get_db)):
    # If new one is primary, demote all others
    if payload.is_primary:
        db.query(BankSettings).filter(BankSettings.is_primary == True).update(
            {"is_primary": False}
        )
    new_settings = BankSettings(**payload.dict())
    db.add(new_settings)
    db.commit()
    db.refresh(new_settings)
    return {"id": str(new_settings.id), "message": "Bank settings created successfully"}


# =====================================================
# ADMIN: UPDATE BANK SETTINGS
# =====================================================

@router.patch("/admin/bank-settings/{settings_id}", dependencies=[Depends(require_admin)])
def update_bank_settings(
    settings_id: str,
    payload: BankSettingsUpdate,
    db: Session = Depends(get_db),
):
    settings = db.query(BankSettings).filter(BankSettings.id == settings_id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Bank settings not found")

    # If setting this as primary, demote all others
    if payload.is_primary:
        db.query(BankSettings).filter(
            BankSettings.is_primary == True,
            BankSettings.id != settings_id,
        ).update({"is_primary": False})

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(settings, field, value)

    db.commit()
    db.refresh(settings)
    return {"id": str(settings.id), "message": "Bank settings updated successfully"}


# =====================================================
# ADMIN: DELETE BANK SETTINGS
# =====================================================

@router.delete("/admin/bank-settings/{settings_id}", dependencies=[Depends(require_admin)])
def delete_bank_settings(settings_id: str, db: Session = Depends(get_db)):
    settings = db.query(BankSettings).filter(BankSettings.id == settings_id).first()
    if not settings:
        raise HTTPException(404, "Bank settings not found")
    db.delete(settings)
    db.commit()
    return {"message": "Bank settings deleted"}


# =====================================================
# ADMIN: REVIEW PAYMENT (approve / reject)
# =====================================================

@router.post("/admin/{payment_id}/review", dependencies=[Depends(require_admin)])
def review_payment(
    payment_id: str,
    payload: PaymentReviewPayload,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    if payload.status not in ("paid", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'paid' or 'rejected'")

    payment = (
        db.query(Payment)
        .options(joinedload(Payment.order))
        .filter(Payment.id == payment_id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status not in (PaymentStatus.on_hold, PaymentStatus.pending):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot review a payment with status '{payment.status.value}'. Only pending/on_hold payments can be reviewed.",
        )

    old_status = payment.status
    new_status = PaymentStatus(payload.status)

    payment.status = new_status
    payment.admin_notes = payload.admin_notes
    payment.reviewed_by = admin.id
    payment.reviewed_at = datetime.now(timezone.utc)
    payment.updated_at = datetime.now(timezone.utc)

    # Sync order status
    if payment.order:
        if payload.status == "paid":
            payment.order.status = OrderStatus.paid
        elif payload.status == "rejected":
            # Roll back order to pending so user can retry
            payment.order.status = OrderStatus.pending

    # Audit trail
    _record_status_history(
        db, payment, old_status, new_status,
        changed_by_id=admin.id,
        reason=payload.admin_notes or f"Admin reviewed: {payload.status}",
    )

    # Notify user
    if payment.order:
        user_id = payment.order.user_id
        if payload.status == "paid":
            _notify_user(
                db, user_id,
                title="Payment Confirmed ✓",
                message=f"Your payment of {payment.amount} has been confirmed. Your order is being processed.",
                link=f"/account/orders/{payment.order_id}",
            )
        else:
            _notify_user(
                db, user_id,
                title="Payment Rejected",
                message=f"Your payment proof was rejected. Reason: {payload.admin_notes or 'Please contact support.'}",
                link=f"/store/payment?order_id={payment.order_id}",
            )

    db.commit()
    db.refresh(payment)

    return {
        "message": f"Payment marked as '{payload.status}'",
        "payment_id": str(payment.id),
        "payment_status": payment.status,
        "order_status": payment.order.status if payment.order else None,
        "reviewed_by": str(payment.reviewed_by),
        "reviewed_at": payment.reviewed_at,
    }


# =====================================================
# ADMIN: GET SINGLE PAYMENT DETAIL
# =====================================================

@router.get("/admin/{payment_id}", dependencies=[Depends(require_admin)])
def admin_get_payment_detail(payment_id: str, db: Session = Depends(get_db)):
    payment = (
        db.query(Payment)
        .options(
            joinedload(Payment.proof),
            joinedload(Payment.order),
            joinedload(Payment.status_history),
        )
        .filter(Payment.id == payment_id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    data = _serialize_payment(payment, include_order=True)
    data["status_history"] = [
        {
            "old_status": h.old_status,
            "new_status": h.new_status,
            "changed_by": str(h.changed_by) if h.changed_by else None,
            "reason": h.reason,
            "created_at": h.created_at,
        }
        for h in sorted(payment.status_history, key=lambda x: x.created_at, reverse=True)
    ]
    return data


# =====================================================
# USER: CREATE PAYMENT FOR ORDER
# =====================================================

@router.post("/{order_id}")
def create_payment(
    order_id: str,
    payload: CreatePaymentPayload = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Create a payment for an order.
    - If a pending/on_hold payment exists → return it (idempotent).
    - If a rejected payment exists → create a new attempt (retry allowed).
    - If order is already paid → 400.
    """
    order = (
        db.query(Order)
        .filter(Order.id == order_id, Order.user_id == user.id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status == OrderStatus.paid:
        raise HTTPException(status_code=400, detail="This order has already been paid.")

    if order.status == OrderStatus.cancelled:
        raise HTTPException(status_code=400, detail="Cannot pay for a cancelled order.")

    if order.status not in (OrderStatus.pending,):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot initiate payment for order in status '{order.status.value}'.",
        )

    # Check for existing active payment
    existing = (
        db.query(Payment)
        .filter(Payment.order_id == order.id)
        .order_by(Payment.created_at.desc())
        .first()
    )

    if existing:
        if existing.status in (PaymentStatus.pending, PaymentStatus.on_hold):
            # Idempotent — return existing payment
            return {
                "payment_id": str(existing.id),
                "order_id": str(order.id),
                "amount": existing.amount,
                "status": existing.status,
                "method": existing.method,
                "reference_number": existing.reference_number,
                "message": "Payment already in progress",
            }
        elif existing.status == PaymentStatus.paid:
            raise HTTPException(400, "This order has already been paid.")
        # If rejected → fall through to create new payment attempt

    # Determine method
    method_str = (payload.method if payload else None) or "bank_transfer"
    try:
        method = PaymentMethod(method_str)
    except ValueError:
        raise HTTPException(400, f"Invalid payment method: '{method_str}'")

    # Generate unique reference number
    ref = f"PAY-{str(uuid.uuid4()).upper()[:8]}"

    payment = Payment(
        order_id=order.id,
        amount=order.total_amount,
        method=method,
        status=PaymentStatus.pending,
        reference_number=ref,
    )
    db.add(payment)

    _record_status_history(
        db, payment, None, PaymentStatus.pending,
        changed_by_id=user.id,
        reason="Payment initiated by user",
    )

    db.commit()
    db.refresh(payment)

    return {
        "payment_id": str(payment.id),
        "order_id": str(order.id),
        "amount": payment.amount,
        "status": payment.status,
        "method": payment.method,
        "reference_number": payment.reference_number,
    }


# =====================================================
# USER: UPDATE PAYMENT METHOD
# =====================================================

@router.patch("/{payment_id}/method")
def update_payment_method(
    payment_id: str,
    payload: UpdatePaymentMethodPayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Allow user to switch payment method before uploading proof."""
    payment = (
        db.query(Payment)
        .join(Order, Payment.order_id == Order.id)
        .filter(Payment.id == payment_id, Order.user_id == user.id)
        .first()
    )
    if not payment:
        raise HTTPException(404, "Payment not found")
    if payment.status != PaymentStatus.pending:
        raise HTTPException(400, "Can only change method on pending payments")

    try:
        payment.method = PaymentMethod(payload.method)
    except ValueError:
        raise HTTPException(400, f"Invalid payment method: '{payload.method}'")

    payment.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Payment method updated", "method": payment.method}


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
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status not in [PaymentStatus.pending, PaymentStatus.on_hold]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot upload proof for payment in status '{payment.status.value}'",
        )

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}
    if proof.content_type not in allowed_types:
        raise HTTPException(400, "Only images (JPEG, PNG, WebP) and PDF files are allowed")

    # Max 10MB
    proof.file.seek(0, 2)
    file_size = proof.file.tell()
    proof.file.seek(0)
    if file_size > 10 * 1024 * 1024:
        raise HTTPException(400, "File size must not exceed 10MB")

    proof_url = handle_upload(file=proof, folder="payments", owner_id=str(payment.id))

    # ✅ FIXED: flush before insert to avoid constraint issues
    if payment.proof:
        db.delete(payment.proof)
        db.flush()

    proof_record = PaymentProof(payment_id=payment.id, file_url=proof_url)
    db.add(proof_record)

    old_status = payment.status
    payment.status = PaymentStatus.on_hold
    payment.updated_at = datetime.now(timezone.utc)

    _record_status_history(
        db, payment, old_status, PaymentStatus.on_hold,
        changed_by_id=user.id,
        reason="Payment proof uploaded by user",
    )

    db.commit()
    db.refresh(proof_record)

    return {
        "message": "Payment proof uploaded successfully. Awaiting admin review.",
        "proof_url": proof_record.file_url,
        "payment_status": payment.status,
        "payment_id": str(payment.id),
    }


# =====================================================
# USER: GET SINGLE PAYMENT DETAIL
# =====================================================

@router.get("/{payment_id}")
def get_payment_detail(
    payment_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    payment = (
        db.query(Payment)
        .join(Order, Payment.order_id == Order.id)
        .options(
            joinedload(Payment.proof),
            joinedload(Payment.status_history),
        )
        .filter(Payment.id == payment_id, Order.user_id == user.id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    data = _serialize_payment(payment)
    data["status_history"] = [
        {
            "old_status": h.old_status,
            "new_status": h.new_status,
            "created_at": h.created_at,
            "reason": h.reason,
        }
        for h in sorted(payment.status_history, key=lambda x: x.created_at)
    ]
    return data