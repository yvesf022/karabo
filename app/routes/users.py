from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from app.database import get_db
from app.models import User
from app.dependencies import get_current_user
from app.cloudinary_client import upload_image

router = APIRouter(prefix="/users", tags=["users"])

# =========================
# AVATAR UPLOAD CONFIG
# =========================

ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


# =========================
# USER: UPLOAD AVATAR (CLOUDINARY)
# =========================

@router.post("/me/avatar", status_code=status.HTTP_200_OK)
def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # -------------------------
    # Validate content type
    # -------------------------
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image type. Only JPG, PNG, and WEBP are allowed.",
        )

    # -------------------------
    # Validate file size (stream-safe)
    # -------------------------
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)

    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image size must be less than 5MB.",
        )

    # -------------------------
    # Upload to Cloudinary
    # -------------------------
    public_id = f"user_{current_user.id}_{uuid.uuid4().hex}"

    avatar_url = upload_image(
        file=file.file,
        folder="avatars",
        public_id=public_id,
        allowed_formats=["jpg", "png", "webp"],
    )

    # -------------------------
    # Update DB
    # -------------------------
    current_user.avatar_url = avatar_url
    db.commit()
    db.refresh(current_user)

    return {"avatar_url": avatar_url}
