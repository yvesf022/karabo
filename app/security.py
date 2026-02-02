import os
from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import HTTPException, status, Request

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
BCRYPT_MAX_BYTES = 72


# =====================================================
# PASSWORD HELPERS
# =====================================================

def _validate_password_length(password: str):
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password too long (max 72 bytes)",
        )


def get_password_hash(password: str) -> str:
    _validate_password_length(password)
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    _validate_password_length(plain)
    return pwd_context.verify(plain, hashed)


# =====================================================
# TOKEN HELPERS (IDENTITY ONLY)
# =====================================================

def create_token(user_id: str) -> str:
    payload = {
        "sub": str(user_id),
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def get_token_from_request(request: Request) -> str:
    return (
        request.cookies.get("admin_access_token")
        or request.cookies.get("access_token")
        or request.headers.get("Authorization", "").replace("Bearer ", "")
    )
