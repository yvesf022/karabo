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
    Non-critical side effect.
    Email failure must NEVER affect user flows.
    """
    try:
        token = create_email_verification_token(str(user.id))
        verify_url = f"{FRONTEND_URL}/verify-email?token={token}"

        success = send_email(
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

        if not success:
            logger.warning(
                "Verification email failed to send | user_id=%s | email=%s",
                user.id,
                user.email,
            )

    except Exception as e:
        logger.warning(
            "Verification email exception swallowed | user_id=%s | error=%s",
            user.id,
            str(e),
        )


# =====================================================
# REGISTER
# =====================================================

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterPayload,
    db: Session = Depends(get_db),
):
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

    return {
        "message": "Account created.",
    }


# =====================================================
# RESEND VERIFICATION
# =====================================================

@router.post("/resend-verification")
def resend_verification(
    payload: ResendVerificationPayload,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or user.is_verified:
        return {
            "message": "If the account exists, a verification email has been sent."
        }

    send_verification_email(user)

    return {
        "message": "If the account exists, a verification email has been sent."
    }


# =====================================================
# VERIFY EMAIL
# =====================================================

@router.get("/verify-email")
def verify_email(
    token: str,
    db: Session = Depends(get_db),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link",
        )

    if payload.get("type") != "email_verification":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token type",
        )

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found",
        )

    if user.is_verified:
        return {"message": "Email already verified"}

    user.is_verified = True
    db.commit()

    return {"message": "Email verified successfully"}


# =====================================================
# LOGIN  ✅ EMAIL VERIFICATION REMOVED
# =====================================================

@router.post("/login")
def login(
    payload: LoginPayload,
    response: Response,
    db: Session = Depends(get_db),
):
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

    # ❌ NO email verification check here anymore

    token = create_token(user.id, user.role)

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="none" if COOKIE_SECURE else "lax",
        path="/",
        max_age=60 * 60 * 24 * 7,
    )

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
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Logged out"}
