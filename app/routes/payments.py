from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from typing import Optional

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


# 🔥 IMPORTANT: NO /api HERE
router = APIRouter(prefix="/payments", tags=["payments"])


# =====================================================
# PUBLIC: GET BANK DETAILS FOR PAYMENT
# =====================================================
@router.get("/bank-details")
def get_bank_details(db: Session = Depends(get_db)):
    """Get active primary bank account details"""

    bank = (
        db.query(BankSettings)
        .filter(BankSettings.is_active == True)
        .order_by(BankSettings.is_primary.desc())
        .first()
    )

    if not bank:
        raise HTTPException(
            status_code=404,
            detail="No payment details configured. Please contact support.",
        )

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
        raise HTTPException(
            status_code=400,
            detail=f"Cannot upload proof for payment in status '{payment.status}'",
        )

    if not proof.content_type.startswith("image/") and proof.content_type != "application/pdf":
        raise HTTPException(400, "Only images and PDF files are allowed")

    proof_url = handle_upload(
        file=proof,
        folder="payments",
        owner_id=str(payment.id),
    )

    if payment.proof:
        db.delete(payment.proof)

    proof_record = PaymentProof(
        payment_id=payment.id,
        file_url=proof_url,
    )

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
# ADMIN: LIST PAYMENTS
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
                {
                    "id": str(p.proof.id),
                    "file_url": p.proof.file_url,
                    "uploaded_at": p.proof.uploaded_at,
                }
                if p.proof
                else None
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
# ADMIN: CREATE OR UPDATE BANK SETTINGS
# =====================================================
@router.post("/admin/bank-settings", dependencies=[Depends(require_admin)])
def create_bank_settings(
    bank_name: str,
    account_name: str,
    account_number: str,
    db: Session = Depends(get_db),
    branch: Optional[str] = None,
    swift_code: Optional[str] = None,
    mobile_money_provider: Optional[str] = None,
    mobile_money_number: Optional[str] = None,
    mobile_money_name: Optional[str] = None,
    qr_code_url: Optional[str] = None,
    instructions: Optional[str] = None,
    is_active: bool = True,
    is_primary: bool = False,
):
    new_settings = BankSettings(
        bank_name=bank_name,
        account_name=account_name,
        account_number=account_number,
        branch=branch,
        swift_code=swift_code,
        mobile_money_provider=mobile_money_provider,
        mobile_money_number=mobile_money_number,
        mobile_money_name=mobile_money_name,
        qr_code_url=qr_code_url,
        instructions=instructions,
        is_active=is_active,
        is_primary=is_primary,
    )

    db.add(new_settings)
    db.commit()
    db.refresh(new_settings)

    return {
        "id": str(new_settings.id),
        "message": "Bank settings created successfully",
    }
