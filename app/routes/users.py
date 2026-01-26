from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session
from pathlib import Path
import shutil

from app.database import get_db
from app.models import User
from app.dependencies import get_current_user

router = APIRouter(prefix="/users", tags=["users"])

# =========================
# AVATAR UPLOAD
# =========================

AVATAR_DIR = Path("static/avatars")
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post(
    "/me/avatar",
    status_code=status.HTTP_200_OK,
)
def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image type. Only JPG, PNG, and WEBP are allowed.",
        )

    contents = file.file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image size must be less than 5MB.",
        )

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)

    extension = ALLOWED_TYPES[file.content_type]
    filename = f"{current_user.id}{extension}"
    filepath = AVATAR_DIR / filename

    with open(filepath, "wb") as buffer:
        buffer.write(contents)

    avatar_url = f"/static/avatars/{filename}"

    current_user.avatar_url = avatar_url
    db.commit()

    return {
        "avatar_url": avatar_url
    }
