from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import User
from app.schemas import LoginSchema, TokenSchema
from app.security import (
    verify_password,
    create_access_token,
    get_current_user,
)
from app.config import settings

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

# =========================
# LOGIN
# =========================
@router.post("/login", response_model=TokenSchema)
def login(payload: LoginSchema, db: Session = Depends(get_db)):
    """
    Unified login endpoint.
    Works for:
    - Admin users
    - Normal users
    """

    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(
        data={
            "sub": user.email,
            "user_id": user.id,
            "role": user.role,
        }
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "email": user.email,
        "role": user.role,
    }


# =========================
# CURRENT USER (SESSION CHECK)
# =========================
@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    """
    Returns the currently authenticated user.
    Used by frontend to verify session & role.
    """
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
    }


# =========================
# ADMIN GUARD (DEPENDENCY)
# =========================
def require_admin(current_user: User = Depends(get_current_user)):
    """
    Dependency to protect admin-only routes.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# =========================
# ADMIN SESSION CHECK (OPTIONAL BUT USEFUL)
# =========================
@router.get("/admin/me")
def admin_me(admin_user: User = Depends(require_admin)):
    """
    Confirms admin authentication.
    Useful for admin dashboard protection.
    """
    return {
        "id": admin_user.id,
        "email": admin_user.email,
        "role": admin_user.role,
    }


# =========================
# HEALTH CHECK (AUTH)
# =========================
@router.get("/health")
def auth_health():
    """
    Simple auth health check.
    """
    return {"status": "auth-ok"}
