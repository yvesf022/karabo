import os
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import User

# ======================================================
# JWT CONFIG
# ======================================================

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7


# ======================================================
# TOKEN DATA SCHEMA
# ======================================================

class TokenData(BaseModel):
    user_id: str
    role: str


# ======================================================
# TOKEN CREATION
# ======================================================

def create_token(user_id: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ======================================================
# TOKEN DECODING (STRING INPUT)
# ======================================================

def decode_token(token: str) -> dict | None:
    """Decode a JWT token string and return the payload."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ======================================================
# TOKEN EXTRACTION & DECODING (REQUEST INPUT)
# ======================================================

def decode_access_token(request: Request) -> TokenData:
    """
    ✅ FIXED: Extract token from request and decode it.
    Returns TokenData object.
    """
    token = (
        request.cookies.get("admin_access_token")
        or request.cookies.get("access_token")
        or request.headers.get("Authorization", "").replace("Bearer ", "")
        or None
    )
    
    if not token:
        raise HTTPException(
            status_code=401, 
            detail="Not authenticated"
        )

    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired token"
        )

    return TokenData(
        user_id=payload["sub"],
        role=payload.get("role", "user")
    )


# ======================================================
# TOKEN EXTRACTION HELPER
# ======================================================

def get_token_from_request(request: Request) -> str | None:
    """Extract token string from request cookies or headers."""
    return (
        request.cookies.get("admin_access_token")
        or request.cookies.get("access_token")
        or request.headers.get("Authorization", "").replace("Bearer ", "")
        or None
    )


# ======================================================
# CURRENT USER
# ======================================================

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User disabled")

    return user


# ======================================================
# ADMIN GUARD
# ======================================================

def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
