import os
from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User


# =====================================================
# SECURITY CONFIG (ENV ONLY)
# =====================================================

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set in environment variables")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7


# =====================================================
# PASSWORD HASHING
# =====================================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
BCRYPT_MAX_BYTES = 72


def _validate_password_length(password: str) -> None:
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too long (maximum 72 bytes allowed).",
        )


def hash_password(password: str) -> str:
    _validate_password_length(password)
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    _validate_password_length(plain_password)
    return pwd_context.verify(plain_password, hashed_password)


# =====================================================
# JWT HANDLING
# =====================================================

def create_token(user_id, role: str) -> str:
    payload = {
        "sub": str(user_id),  # UUID → str
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# =====================================================
# AUTH HELPERS
# =====================================================

def get_token_from_request(request: Request) -> str | None:
    # 1️⃣ Try HTTP-only cookie (PRIMARY)
    token = request.cookies.get("access_token")
    if token:
        return token

    # 2️⃣ Fallback: Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]

    return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):
    token = get_token_from_request(request)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


def require_admin(
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
