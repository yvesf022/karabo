from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models import User, PaymentSetting

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------
# ADMIN: VERIFY ACCESS
# ---------------------------------
@router.get("/me")
def admin_me(admin: User = Depends(require_admin)):
    return {
        "id": admin.id,
        "email": admin.email,
        "role": admin.role,
        "message": "Admin access confirmed",
    }


# ---------------------------------
# ADMIN: GET PAYMENT SETTINGS
# ---------------------------------
@router.get("/payment-settings")
def get_payment_settings(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    settings = db.query(PaymentSetting).all()
    return [
        {
            "id": s.id,
            "bank_name": s.bank_name,
            "account_name": s.account_name,
            "account_number": s.account_number,
            "is_active": s.is_active,
        }
        for s in settings
    ]


# ---------------------------------
# ADMIN: CREATE / UPDATE BANK DETAILS
# ---------------------------------
@router.post("/payment-settings")
def upsert_payment_setting(
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    bank_name = payload.get("bank_name")
    account_name = payload.get("account_name")
    account_number = payload.get("account_number")
    is_active = payload.get("is_active", True)

    if not bank_name or not account_name or not account_number:
        raise HTTPException(
            status_code=400,
            detail="Missing bank payment details",
        )

    setting = db.query(PaymentSetting).first()

    if setting:
        setting.bank_name = bank_name
        setting.account_name = account_name
        setting.account_number = account_number
        setting.is_active = is_active
    else:
        setting = PaymentSetting(
            bank_name=bank_name,
            account_name=account_name,
            account_number=account_number,
            is_active=is_active,
        )
        db.add(setting)

    db.commit()

    return {"message": "Payment settings saved"}
