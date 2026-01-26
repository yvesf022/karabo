import os
import uuid
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models import User, PaymentSetting

router = APIRouter(prefix="/admin", tags=["admin"])

# ==============================
# UPLOAD CONFIG
# ==============================
UPLOAD_DIR = "uploads/products"
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}


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


# ---------------------------------
# ADMIN: UPLOAD PRODUCT IMAGE
# ---------------------------------
@router.post("/products/upload-image")
def upload_product_image(
    image: UploadFile = File(...),
    admin: User = Depends(require_admin),
):
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid image type",
        )

    ext = os.path.splitext(image.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    try:
        with open(filepath, "wb") as f:
            f.write(image.file.read())
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to save image",
        )

    return {
        "url": f"/{UPLOAD_DIR}/{filename}",
    }
