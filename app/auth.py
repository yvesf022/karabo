import os
import logging
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from jose import jwt

from app.database import get_db
from app.models import User
from app.security import (
    verify_password,
    hash_password,
    create_token,
    get_current_user,
)
from app.utils.email import send_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

logger = logging.getLogger(__name__)

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

EMAIL_VERIFY_EXPIRE_MINUTES = 30


# =====================================================
# SCHEMAS
# =====================================================

class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class RegisterPayload(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    phone: str | None = None


class ResendVerificationPayload(BaseModel):
    email: EmailStr


# =====================================================
# HELPERS
# =====================================================

def create_email_verification_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "email_verification",
        "exp": jwt.datetime.utcnow()
        + timedelta(minutes=EMAIL_VERIFY_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def send_verification_email(user: User):
    """
    Non-blocking email send.
    Email failure MUST NOT break auth flow.
    """
    try:
        token = create_email_verification_token(str(user.id))
        verify_url = f"{FRONTEND_URL}/verify-email?token={token}"

        send_email(
            to_email=user.email,
            subject="Verify your email address",
            html_content=f"""
            <h2>Karabo Online Store</h2>
            <p>Please verify your email address:</p>
            <p><a href="{verify_url}">Verify Email</a></p>
            <p>This link expires in 30 minutes.</p>
            """,
            text_content=f"Verify your email: {verify_url}",
        )
    except Exception as e:
        logger.warning(
            "Verification email failed | user_id=%s | error=%s",
            user.id,
            str(e),
        )


# =====================================================
# REGISTER
# =====================================================

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterPayload, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        role="user",
        is_active=True,
        is_verified=False,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    send_verification_email(user)

    return {"message": "Account created."}


# =====================================================
# LOGIN
# =====================================================

@router.post("/login")
def login(payload: LoginPayload, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User disabled",
        )

    token = create_token(user.id, user.role)

    # ✅ FIXED COOKIE POLICY
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",      # 🔥 CRITICAL FIX
        path="/",
        max_age=60 * 60 * 24 * 7,
    )

    response.headers["Cache-Control"] = "no-store"

    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
    }


# =====================================================
# CURRENT USER
# =====================================================

@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_verified": user.is_verified,
    }


# =====================================================
# LOGOUT
# =====================================================

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key="access_token",
        path="/",
        secure=COOKIE_SECURE,
        samesite="lax",      # 🔥 MUST MATCH SET COOKIE
    )
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Logged out"}
