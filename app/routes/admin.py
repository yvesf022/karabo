from fastapi import APIRouter, Depends
from app.dependencies import require_admin
from app.models import User

router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------
# ADMIN: VERIFY ACCESS
# ---------------------------------
@router.get("/me")
def admin_me(admin: User = Depends(require_admin)):
    """
    Simple admin-only endpoint to confirm:
    - JWT is valid
    - User exists in DB
    - Role === admin
    """
    return {
        "id": str(admin.id),
        "email": admin.email,
        "role": admin.role,
        "message": "Admin access confirmed",
    }
from app.models import PaymentSetting
from sqlalchemy.orm import Session
from app.database import get_db
from fastapi import HTTPException, status

# ---------------------------------
# ADMIN: GET PAYMENT SETTINGS
# ---------------------------------
@router.get("/payment-settings")
def get_payment_settings(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    settings = db.query(PaymentSetting).all()
    return settings


# ---------------------------------
# ADMIN: CREATE / UPDATE BANK DETAILS
# ---------------------------------
@router.post("/payment-settings")
def upsert_payment_setting(
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    method = payload.get("method", "bank_transfer")

    setting = db.query(PaymentSetting).filter(
        PaymentSetting.method == method
    ).first()

    if setting:
        # update existing
        setting.provider_name = payload["provider_name"]
        setting.account_name = payload["account_name"]
        setting.account_number = payload["account_number"]
        setting.instructions = payload.get("instructions")
        setting.is_active = payload.get("is_active", True)
    else:
        # create new
        setting = PaymentSetting(
            method=method,
            provider_name=payload["provider_name"],
            account_name=payload["account_name"],
            account_number=payload["account_number"],
            instructions=payload.get("instructions"),
            is_active=True,
        )
        db.add(setting)

    db.commit()

    return {"message": "Payment settings saved"}

