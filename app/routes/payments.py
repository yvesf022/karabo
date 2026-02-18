from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import (
    Payment,
    PaymentProof,
    PaymentStatus,
    PaymentMethod,
    Order,
    OrderStatus,
    BankSettings,
)
from app.uploads.service import handle_upload


router = APIRouter(prefix="/payments", tags=["payments"])


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


# =====================================================
# PUBLIC: GET BANK DETAILS FOR PAYMENT
# =====================================================
@router.get("/bank-details")
def get_bank_details(db: Session = Depends(get_db)):
    bank = (
        db.query(BankSettings)
        .filter(BankSettings.is_active == True)
        .order_by(BankSettings.is_primary.desc())
        .first()
    )
    if not bank:
        raise HTTPException(status_code=404, detail="No payment details configured. Please contact support.")
    return {
        "bank_name": bank.bank_name,
        "account_name": bank.account_name,
        "account_number": bank.account_number,
        "branch": bank.branch,
        "swift_code": bank.swift_code,
        "mobile_money_provider": bank.mobile_money_provider,
        "mobile_money_number": bank.mobile_money_number,
        "mobile_money_name": bank.mobile_money_name,
        "qr_code_url": bank.qr_code_url,
        "instructions": bank.instructions,
    }


# =====================================================
# USER: GET MY PAYMENTS
# (must be before /{payment_id} to avoid route conflict)
# =====================================================
@router.get("/my")
def get_my_payments(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    payments = (
        db.query(Payment)
        .join(Order, Payment.order_id == Order.id)
        .options(joinedload(Payment.proof))
        .filter(Order.user_id == user.id)
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
                {"id": str(p.proof.id), "file_url": p.proof.file_url, "uploaded_at": p.proof.uploaded_at}
                if p.proof else None
            ),
            "created_at": p.created_at,
        }
        for p in payments
    ]


# =====================================================
# ADMIN: LIST PAYMENTS
# (must be before /{payment_id} to avoid route conflict)
# =====================================================
@router.get("/admin", dependencies=[Depends(require_admin)])
def admin_list_payments(
    db: Session = Depends(get_db),
    status_filter: Optional[str] = None,
):
    query = (
        db.query(Payment)
        .options(joinedload(Payment.proof), joinedload(Payment.order))
        .order_by(Payment.created_at.desc())
    )
    if status_filter:
        try:
            query = query.filter(Payment.status == PaymentStatus(status_filter))
        except ValueError:
            pass
    payments = query.all()
    return [
        {
            "id": str(p.id),
            "order_id": str(p.order_id),
            "amount": p.amount,
            "status": p.status,
            "method": p.method,
            "proof": (
                {"id": str(p.proof.id), "file_url": p.proof.file_url, "uploaded_at": p.proof.uploaded_at}
                if p.proof else None
            ),
            "admin_notes": p.admin_notes,
            "reviewed_by": str(p.reviewed_by) if p.reviewed_by else None,
            "reviewed_at": p.reviewed_at,
            "created_at": p.created_at,
        }
        for p in payments
    ]


# =====================================================
# ADMIN: GET BANK SETTINGS
# (must be before /admin/{payment_id} to avoid conflict)
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
        }
        for s in settings
    ]


# =====================================================
# ADMIN: CREATE BANK SETTINGS
# =====================================================
@router.post("/admin/bank-settings", dependencies=[Depends(require_admin)])
def create_bank_settings(payload: BankSettingsCreate, db: Session = Depends(get_db)):
    new_settings = BankSettings(**payload.dict())
    db.add(new_settings)
    db.commit()
    db.refresh(new_settings)
    return {"id": str(new_settings.id), "message": "Bank settings created successfully"}


# =====================================================
# ADMIN: UPDATE BANK SETTINGS
# =====================================================
@router.patch("/admin/bank-settings/{settings_id}", dependencies=[Depends(require_admin)])
def update_bank_settings(settings_id: str, payload: BankSettingsUpdate, db: Session = Depends(get_db)):
    settings = db.query(BankSettings).filter(BankSettings.id == settings_id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Bank settings not found")
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    return {"id": str(settings.id), "message": "Bank settings updated successfully"}


# =====================================================
# ADMIN: REVIEW PAYMENT (approve / reject)
# (must be before /admin/{payment_id} to avoid conflict)
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
        raise HTTPException(status_code=400, detail=f"Cannot review a payment with status '{payment.status}'")

    payment.status = PaymentStatus(payload.status)
    payment.admin_notes = payload.admin_notes
    payment.reviewed_by = admin.id
    payment.reviewed_at = datetime.now(timezone.utc)

    if payload.status == "paid" and payment.order:
        payment.order.status = OrderStatus.paid

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
def admin_get_payment_detail(
    payment_id: str,
    db: Session = Depends(get_db),
):
    payment = (
        db.query(Payment)
        .options(joinedload(Payment.proof), joinedload(Payment.order))
        .filter(Payment.id == payment_id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {
        "id": str(payment.id),
        "order_id": str(payment.order_id),
        "amount": payment.amount,
        "status": payment.status,
        "method": payment.method,
        "proof": (
            {"id": str(payment.proof.id), "file_url": payment.proof.file_url, "uploaded_at": payment.proof.uploaded_at}
            if payment.proof else None
        ),
        "admin_notes": payment.admin_notes,
        "reviewed_by": str(payment.reviewed_by) if payment.reviewed_by else None,
        "reviewed_at": payment.reviewed_at,
        "created_at": payment.created_at,
        "order": {
            "id": str(payment.order.id),
            "status": payment.order.status,
            "total_amount": payment.order.total_amount,
        } if payment.order else None,
    }


# =====================================================
# USER: CREATE PAYMENT
# (wildcard /{order_id} — must come AFTER all static routes)
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
        raise HTTPException(status_code=400, detail=f"Cannot pay for order in status '{order.status}'")

    existing = db.query(Payment).filter(Payment.order_id == order.id).first()
    if existing:
        return {
            "payment_id": str(existing.id),
            "order_id": str(order.id),
            "amount": existing.amount,
            "status": existing.status,
            "message": "Payment already exists",
        }

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
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status not in [PaymentStatus.pending, PaymentStatus.on_hold]:
        raise HTTPException(status_code=400, detail=f"Cannot upload proof for payment in status '{payment.status}'")
    if not proof.content_type.startswith("image/") and proof.content_type != "application/pdf":
        raise HTTPException(400, "Only images and PDF files are allowed")

    proof_url = handle_upload(file=proof, folder="payments", owner_id=str(payment.id))

    if payment.proof:
        db.delete(payment.proof)

    proof_record = PaymentProof(payment_id=payment.id, file_url=proof_url)
    payment.status = PaymentStatus.on_hold
    db.add(proof_record)
    db.commit()
    db.refresh(proof_record)

    return {
        "message": "Payment proof uploaded successfully",
        "proof_url": proof_record.file_url,
        "payment_status": payment.status,
    }


# =====================================================
# USER: GET SINGLE PAYMENT DETAIL
# (wildcard — must be LAST)
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
        .options(joinedload(Payment.proof))
        .filter(Payment.id == payment_id, Order.user_id == user.id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {
        "id": str(payment.id),
        "order_id": str(payment.order_id),
        "amount": payment.amount,
        "status": payment.status,
        "method": payment.method,
        "proof": (
            {"id": str(payment.proof.id), "file_url": payment.proof.file_url, "uploaded_at": payment.proof.uploaded_at}
            if payment.proof else None
        ),
        "admin_notes": payment.admin_notes,
        "reviewed_at": payment.reviewed_at,
        "created_at": payment.created_at,
    }