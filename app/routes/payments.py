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

router = APIRouter(prefix="/api/payments", tags=["payments"])


# =====================================================
# PUBLIC: GET BANK DETAILS FOR PAYMENT
# =====================================================
@router.get("/bank-details")
def get_bank_details(db: Session = Depends(get_db)):
    """Get active bank account details for manual payment"""
    
    # Get primary bank settings or first active
    bank = (
        db.query(BankSettings)
        .filter(BankSettings.is_active == True)
        .filter(BankSettings.is_primary == True)
        .first()
    )
    
    if not bank:
        bank = (
            db.query(BankSettings)
            .filter(BankSettings.is_active == True)
            .first()
        )
    
    if not bank:
        raise HTTPException(
            status_code=404,
            detail="No payment details configured. Please contact support."
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

    # Validate file type
    if not proof.content_type.startswith('image/') and proof.content_type != 'application/pdf':
        raise HTTPException(400, "Only images and PDF files are allowed")

    # Validate file size (15MB max)
    if proof.size and proof.size > 15 * 1024 * 1024:
        raise HTTPException(400, "File size must be less than 15MB")

    proof_url = handle_upload(
        file=proof,
        folder="payments",
        owner_id=str(payment.id),
    )

    # Delete old proof if exists
    if payment.proof:
        db.delete(payment.proof)

    proof_record = PaymentProof(
        payment_id=payment.id,
        file_url=proof_url,
    )

    # Update payment status to on_hold (awaiting review)
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
# ADMIN: GET PAYMENT DETAILS
# =====================================================
@router.get("/admin/{payment_id}", dependencies=[Depends(require_admin)])
def get_payment_details(payment_id: str, db: Session = Depends(get_db)):
    payment = (
        db.query(Payment)
        .options(joinedload(Payment.proof), joinedload(Payment.order))
        .filter(Payment.id == payment_id)
        .first()
    )
    
    if not payment:
        raise HTTPException(404, "Payment not found")

    return {
        "id": str(payment.id),
        "order_id": str(payment.order_id),
        "amount": payment.amount,
        "status": payment.status,
        "method": payment.method,
        "proof": (
            {
                "id": str(payment.proof.id),
                "file_url": payment.proof.file_url,
                "uploaded_at": payment.proof.uploaded_at,
            }
            if payment.proof
            else None
        ),
        "admin_notes": payment.admin_notes,
        "reviewed_by": str(payment.reviewed_by) if payment.reviewed_by else None,
        "reviewed_at": payment.reviewed_at,
        "created_at": payment.created_at,
        "order": {
            "id": str(payment.order.id),
            "total_amount": payment.order.total_amount,
            "status": payment.order.status,
            "created_at": payment.order.created_at,
        },
    }


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

    if payment.status not in [PaymentStatus.pending, PaymentStatus.on_hold]:
        raise HTTPException(
            status_code=400,
            detail=f"Payment already reviewed (status: {payment.status})",
        )

    new_status = payload.get("status")
    admin_notes = payload.get("notes", "")

    if new_status not in (PaymentStatus.paid.value, PaymentStatus.rejected.value):
        raise HTTPException(
            status_code=400,
            detail="Invalid payment status. Use 'paid' or 'rejected'",
        )

    # Update payment
    payment.status = PaymentStatus(new_status)
    payment.admin_notes = admin_notes
    payment.reviewed_by = admin.id
    payment.reviewed_at = datetime.utcnow()

    # Update order status
    if new_status == PaymentStatus.paid.value:
        order.status = OrderStatus.paid
    else:
        order.status = OrderStatus.cancelled

    db.commit()

    # TODO: Send email notification to customer

    return {
        "payment_id": str(payment.id),
        "payment_status": payment.status,
        "order_id": str(order.id),
        "order_status": order.status,
        "message": f"Payment {'approved' if new_status == 'paid' else 'rejected'} successfully",
    }


# =====================================================
# ADMIN: GET BANK SETTINGS
# =====================================================
@router.get("/admin/bank-settings", dependencies=[Depends(require_admin)])
def get_bank_settings(db: Session = Depends(get_db)):
    """Get all bank settings"""
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
# ADMIN: CREATE/UPDATE BANK SETTINGS
# =====================================================
@router.post("/admin/bank-settings", dependencies=[Depends(require_admin)])
def create_bank_settings(payload: dict, db: Session = Depends(get_db)):
    """Create or update bank settings"""
    
    # If setting as primary, unset other primaries
    if payload.get("is_primary"):
        db.query(BankSettings).update({"is_primary": False})
    
    bank = BankSettings(
        bank_name=payload.get("bank_name", ""),
        account_name=payload.get("account_name", ""),
        account_number=payload.get("account_number", ""),
        branch=payload.get("branch"),
        swift_code=payload.get("swift_code"),
        mobile_money_provider=payload.get("mobile_money_provider"),
        mobile_money_number=payload.get("mobile_money_number"),
        mobile_money_name=payload.get("mobile_money_name"),
        qr_code_url=payload.get("qr_code_url"),
        instructions=payload.get("instructions"),
        is_active=payload.get("is_active", True),
        is_primary=payload.get("is_primary", False),
    )
    
    db.add(bank)
    db.commit()
    db.refresh(bank)
    
    return {
        "id": str(bank.id),
        "message": "Bank settings created successfully",
    }


# =====================================================
# ADMIN: UPDATE BANK SETTINGS
# =====================================================
@router.patch("/admin/bank-settings/{bank_id}", dependencies=[Depends(require_admin)])
def update_bank_settings(
    bank_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Update existing bank settings"""
    bank = db.query(BankSettings).filter(BankSettings.id == bank_id).first()
    if not bank:
        raise HTTPException(404, "Bank settings not found")
    
    # If setting as primary, unset other primaries
    if payload.get("is_primary") and not bank.is_primary:
        db.query(BankSettings).filter(BankSettings.id != bank_id).update({"is_primary": False})
    
    # Update fields
    for key, value in payload.items():
        if hasattr(bank, key):
            setattr(bank, key, value)
    
    bank.updated_at = datetime.utcnow()
    db.commit()
    
    return {"message": "Bank settings updated successfully"}


# =====================================================
# ADMIN: DELETE BANK SETTINGS
# =====================================================
@router.delete("/admin/bank-settings/{bank_id}", dependencies=[Depends(require_admin)])
def delete_bank_settings(bank_id: str, db: Session = Depends(get_db)):
    """Delete bank settings"""
    bank = db.query(BankSettings).filter(BankSettings.id == bank_id).first()
    if not bank:
        raise HTTPException(404, "Bank settings not found")
    
    db.delete(bank)
    db.commit()
    
    return {"message": "Bank settings deleted successfully"}


# =====================================================
# ADMIN: UPLOAD QR CODE
# =====================================================
@router.post("/admin/bank-settings/{bank_id}/qr-code", dependencies=[Depends(require_admin)])
def upload_qr_code(
    bank_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload QR code image for bank settings"""
    bank = db.query(BankSettings).filter(BankSettings.id == bank_id).first()
    if not bank:
        raise HTTPException(404, "Bank settings not found")
    
    if not file.content_type.startswith('image/'):
        raise HTTPException(400, "Only image files are allowed")
    
    qr_url = handle_upload(
        file=file,
        folder="qr-codes",
        owner_id=bank_id,
    )
    
    bank.qr_code_url = qr_url
    db.commit()
    
    return {
        "qr_code_url": qr_url,
        "message": "QR code uploaded successfully",
    }