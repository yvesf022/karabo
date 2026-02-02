from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import verify_password, create_token, require_admin

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


class AdminLoginPayload(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def admin_login(
    payload: AdminLoginPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Admin login:
    - Admin must already exist (bootstrapped on startup)
    - Credentials verified against DB
    - Sets HTTP-only admin cookie
    """

    admin = (
        db.query(User)
        .filter(
            User.email == payload.email,
            User.role == "admin",
            User.is_active == True,
        )
        .first()
    )

    if not admin:
        # Do NOT leak whether email exists
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(payload.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(
        user_id=str(admin.id),
        role="admin",
    )

    response.set_cookie(
        key="admin_access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=60 * 60 * 8,  # 8 hours
    )

    return {
        "id": str(admin.id),
        "email": admin.email,
        "role": "admin",
    }


@router.post("/logout")
def admin_logout(response: Response):
    """
    Clears admin session cookie
    """
    response.delete_cookie(
        key="admin_access_token",
        path="/",
        secure=True,
        samesite="none",
    )
    return {"message": "Admin logged out"}


@router.get("/me")
def admin_me(admin: User = Depends(require_admin)):
    """
    Source of truth for admin session
    """
    return {
        "id": str(admin.id),
        "email": admin.email,
        "role": "admin",
    }
