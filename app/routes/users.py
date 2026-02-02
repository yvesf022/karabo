from fastapi import APIRouter, Depends, UploadFile, File, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.dependencies import get_current_user
from app.uploads.service import handle_upload

router = APIRouter(prefix="/users", tags=["users"])


# ======================================================
# USER: UPLOAD AVATAR (CENTRALIZED UPLOAD SERVICE)
# ======================================================

@router.post("/me/avatar", status_code=status.HTTP_200_OK)
def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    avatar_url = handle_upload(
        file=file,
        folder="avatars",
        owner_id=str(current_user.id),
    )

    current_user.avatar_url = avatar_url
    db.commit()
    db.refresh(current_user)

    return {
        "avatar_url": avatar_url,
        "user_id": str(current_user.id),
    }
