import os
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import verify_password, hash_password, create_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

logger = logging.getLogger(__name__)

COOKIE_SECURE = True  # 🔥 MUST be true for SameSite=None

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
# LOGIN
# =========================

@router.post("/login")
def login(payload: LoginPayload, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User disabled")

    token = create_token(user.id, user.role)

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
        "role": user.role,
    }


# =========================
# LOGOUT
# =========================

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key="access_token",
        path="/",
        secure=True,
        samesite="none",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Logged out"}
