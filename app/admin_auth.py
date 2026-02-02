import os
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import verify_password, get_password_hash, create_token
from app.dependencies import require_admin

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])

# =====================================================
# ADMIN BOOTSTRAP (RUNS ON STARTUP)
# =====================================================

def ensure_admin_exists(db: Session):
    """
    Ensures exactly one admin user exists.
    Admin credentials come ONLY from environment variables.
    Safe and idempotent on every startup.
    """

    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")

    if not admin_email or not admin_password:
        print("⚠️ ADMIN_EMAIL or ADMIN_PASSWORD not set — admin bootstrap skipped")
        return

    admin = db.query(User).filter(User.email == admin_email).first()

    if admin:
        # 🔒 Self-heal admin flag if needed
        if not admin.is_admin:
            admin.is_admin = True
            db.commit()
            print("⚠️ Existing user upgraded to admin")
        else:
            print("ℹ️ Admin already exists")
        return

    admin = User(
        email=admin_email,
        hashed_password=get_password_hash(admin_password),
        is_admin=True,
        is_active=True,
    )

    db.add(admin)
    db.commit()

    print("✅ Admin user created from environment variables")


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
            User.is_admin == True,
            User.is_active == True,
        )
        .first()
    )

    if not admin or not verify_password(payload.password, admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
        )

    token = create_token(user_id=str(admin.id))

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
        "is_admin": True,
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
        "is_admin": True,
    }
