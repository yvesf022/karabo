from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import verify_password, create_token, hash_password
from app.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


# =========================
# REGISTER (USER)
# =========================
@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: dict, db: Session = Depends(get_db)):
    email = payload.get("email")
    password = payload.get("password")

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required",
        )

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )

    user = User(
        email=email,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(
        user_id=user.id,
        role=user.role,
    )

    return {
        "message": "Account created successfully",
        "access_token": token,
        "token_type": "bearer",
        "email": user.email,
        "role": user.role,
    }


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

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    token = create_token(
        user_id=user.id,
        role=user.role,
    )

    return {
        "message": "Login successful",
        "access_token": token,
        "token_type": "bearer",
        "email": user.email,
        "role": user.role,
    }


# =========================
# CURRENT USER
# =========================
@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
    }


# =========================
# AUTH HEALTH
# =========================
@router.get("/health")
def auth_health():
    return {
        "status": "auth-ok",
        "message": "Authentication service running",
    }
