from fastapi import APIRouter, Depends, UploadFile, File, status, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.models import User
from app.dependencies import get_current_user
from app.uploads.service import handle_upload

router = APIRouter(prefix="/users", tags=["users"])


# =====================================================
# Pydantic Schemas
# =====================================================

class UpdateMePayload(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None


# =====================================================
# USER: GET MY PROFILE
# =====================================================

@router.get("/me", status_code=status.HTTP_200_OK)
def get_me(
    current_user: User = Depends(get_current_user),
):
    """Return the current user's profile."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "phone": current_user.phone,
        "avatar_url": current_user.avatar_url,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at,
    }


# =====================================================
# ✅ NEW — USER: UPDATE MY PROFILE
# PATCH /api/users/me
# =====================================================

@router.patch("/me", status_code=status.HTTP_200_OK)
def update_me(
    payload: UpdateMePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update the current user's profile fields.
    Only full_name and phone are editable by the user.
    Email and role changes require admin action.
    """
    updated_fields = payload.dict(exclude_unset=True)

    if not updated_fields:
        raise HTTPException(
            status_code=400,
            detail="No fields provided for update",
        )

    for field, value in updated_fields.items():
        setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)

    return {
        "message": "Profile updated successfully",
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "phone": current_user.phone,
        "avatar_url": current_user.avatar_url,
    }


# =====================================================
# USER: UPLOAD AVATAR (CENTRALIZED UPLOAD SERVICE)
# =====================================================

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