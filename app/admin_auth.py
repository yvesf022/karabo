import os
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import (
    verify_password,
    create_token,
    require_admin,
    get_password_hash,
)

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])

# =====================================================
# ADMIN BOOTSTRAP (ENV-BASED)
# =====================================================

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")


def ensure_admin_exists(db: Session):
    """
    Ensure a single admin account exists.
    Safe to run on every startup.
    """

    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        raise RuntimeError(
            "ADMIN_EMAIL and ADMIN_PASSWORD must be set in environment variables"
        )

    admin = (
        db.query(User)
        .filter(User.email == ADMIN_EMAIL, User.role == "admin")
        .first()
    )

    if admin:
        return  # Admin already exists

    admin = User(
        email=ADMIN_EMAIL,
        hashed_password=get_password_hash(ADMIN_PASSWORD),
        role="admin",
        is_active=True,
    )

    db.add(admin)
    db.commit()


# =====================================================
# LOGIN SCHEMA
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


# =====================================================
# ADMIN LOGOUT
# =====================================================

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


# =====================================================
# ADMIN SESSION (SOURCE OF TRUTH)
# =====================================================

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
