from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import verify_password, create_token
from app.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


# =========================
# LOGIN (ADMIN + USER)
# =========================
@router.post("/login")
def login(payload: dict, db: Session = Depends(get_db)):
    email = payload.get("email")
    password = payload.get("password")

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required",
        )

    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_token(
        user_id=user.id,
        role=user.role,
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
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
    }


# =========================
# AUTH HEALTH CHECK
# =========================
@router.get("/health")
def auth_health():
    return {"status": "auth-ok"}
