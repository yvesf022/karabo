import os
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import (
    verify_password,
    hash_password,
    create_token,
    require_admin,
)

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


# =====================================================
# ADMIN BOOTSTRAP (RUN ON STARTUP)
# =====================================================

def ensure_admin_exists(db: Session):
    """
    Ensures a single admin user exists.
    Admin credentials are sourced ONLY from env vars.
    """

    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")

    if not admin_email or not admin_password:
        # Do NOT crash production if admin envs are missing
        return

    existing = (
        db.query(User)
        .filter(User.email == admin_email, User.role == "admin")
        .first()
    )

    if existing:
        return

    admin = User(
        email=admin_email,
        hashed_password=hash_password(admin_password),
        role="admin",
        is_active=True,
    )

    db.add(admin)
    db.commit()


# =====================================================
# SCHEMAS
# =====================================================

class AdminLoginPayload(BaseModel):
    email: EmailStr
    password: str


# =====================================================
# ROUTES
# =====================================================

@router.post("/login")
def admin_login(
    payload: AdminLoginPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    admin = (
        db.query(User)
        .filter(
            User.email == payload.email,
            User.role == "admin",
            User.is_active == True,
        )
        .first()
    )

    if not admin or not verify_password(
        payload.password,
        admin.hashed_password,
    ):
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
    response.delete_cookie(
        key="admin_access_token",
        path="/",
        secure=True,
        samesite="none",
    )
    return {"message": "Admin logged out"}


@router.get("/me")
def admin_me(admin: User = Depends(require_admin)):
    return {
        "id": str(admin.id),
        "email": admin.email,
        "role": "admin",
    }
