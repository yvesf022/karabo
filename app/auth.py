import logging
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.passwords import hash_password, verify_password
from app.security import create_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


# =========================
# SCHEMAS
# =========================

class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class RegisterPayload(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    phone: str | None = None


# =========================
# REGISTER
# =========================

@router.post("/register")
def register(payload: RegisterPayload, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        role="user",
        is_active=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
    }


# =========================
# LOGIN — returns token in body for cross-origin frontends
# =========================

@router.post("/login")
def login(
    payload: LoginPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User disabled",
        )

    token = create_token(user_id=str(user.id), role=user.role)

    # Still set cookie for same-origin / Postman use
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=60 * 60 * 24 * 7,
    )
    response.headers["Cache-Control"] = "no-store"

    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role,
        # ✅ TOKEN IN BODY — frontend stores this in localStorage
        # and sends as Authorization: Bearer <token>
        "access_token": token,
        "token_type": "bearer",
    }


# =========================
# ME
# =========================

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role,
        "created_at": user.created_at,
        "avatar_url": getattr(user, "avatar_url", None),
    }


# =========================
# LOGOUT
# =========================

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="access_token", path="/", secure=True, samesite="none")
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Logged out"}