from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.uploads.service import handle_upload

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    url = handle_upload(
        file=file,
        folder="avatars",
        owner_id=str(user.id),
    )

    user.avatar_url = url
    db.commit()
    db.refresh(user)

    return {"avatar_url": url}


@router.post("/product-image/{product_id}")
def upload_product_image(
    product_id: str,
    file: UploadFile = File(...),
    admin = Depends(require_admin),
):
    url = handle_upload(
        file=file,
        folder="products",
        owner_id=product_id,
    )

    return {"url": url}


@router.post("/payment-proof/{payment_id}")
def upload_payment_proof(
    payment_id: str,
    file: UploadFile = File(...),
    user = Depends(get_current_user),
):
    url = handle_upload(
        file=file,
        folder="payments",
        owner_id=payment_id,
    )

    return {"url": url}
