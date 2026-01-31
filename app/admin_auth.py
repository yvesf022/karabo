import os
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import (
    verify_password,
    create_token,
    require_admin,
)

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"


# =====================================================
# SCHEMA
# =====================================================

class AdminLoginPayload(BaseModel):
    email: EmailStr
    password: str


# =====================================================
# ADMIN LOGIN
# =====================================================

@router.post("/login")
def admin_login(
    payload: AdminLoginPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    admin = db.query(User).filter(User.email == payload.email).first()

    if not admin or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not admin.is_active or admin.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access denied",
        )

    token = create_token(admin.id, admin.role)

    response.set_cookie(
        key="admin_access_token",
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="none" if COOKIE_SECURE else "lax",
        path="/",
        max_age=60 * 60 * 8,  # 8 hours
    )

    return {
        "id": str(admin.id),
        "email": admin.email,
        "role": "admin",
    }


# =====================================================
# ADMIN LOGOUT
# =====================================================

@router.post("/logout")
def admin_logout(response: Response):
    response.delete_cookie(
        key="admin_access_token",
        path="/",
    )
    return {"message": "Admin logged out"}


# =====================================================
# ADMIN ME
# =====================================================

@router.get("/me")
def admin_me(admin: User = Depends(require_admin)):
    return {
        "id": str(admin.id),
        "email": admin.email,
        "role": "admin",
    }
