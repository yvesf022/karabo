from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session
from pathlib import Path
import os

from app.database import get_db
from app.models import User
from app.dependencies import get_current_user

router = APIRouter(prefix="/users", tags=["users"])

# =========================
# AVATAR UPLOAD CONFIG
# =========================

AVATAR_DIR = Path("static/avatars")
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


# =========================
# USER: UPLOAD AVATAR
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
    # Read file safely
    # -------------------------
    contents = file.file.read()
    file.file.close()

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image size must be less than 5MB.",
        )

    # -------------------------
    # Prepare storage
    # -------------------------
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)

    extension = ALLOWED_TYPES[file.content_type]
    filename = f"{current_user.id}{extension}"
    filepath = AVATAR_DIR / filename

    # -------------------------
    # Remove old avatar if exists
    # -------------------------
    if current_user.avatar_url:
        old_path = Path(current_user.avatar_url.lstrip("/"))
        if old_path.exists() and old_path.is_file():
            try:
                old_path.unlink()
            except Exception:
                pass  # Do not block avatar update

    # -------------------------
    # Write new avatar (atomic overwrite)
    # -------------------------
    with open(filepath, "wb") as buffer:
        buffer.write(contents)

    avatar_url = f"/static/avatars/{filename}"

    current_user.avatar_url = avatar_url
    db.commit()

    return {"avatar_url": avatar_url}
