from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import hash_password, verify_password, create_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


# =============================
# SCHEMAS
# =============================

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# =============================
# REGISTER (CUSTOMER ONLY)
# =============================

@router.post("/register", status_code=201)
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)):
    # 1️⃣ Password confirmation
    if payload.password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match",
        )

    # 2️⃣ Check existing user
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # 3️⃣ Create user (customer by default)
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role="customer",
        is_active=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "status": "success",
        "message": "Account created successfully",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
        },
    }


# =============================
# LOGIN (CUSTOMER + ADMIN)
# =============================

@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    token = create_token(user.id, user.role)

    return {
        "status": "success",
        "token": token,
        "role": user.role,
        "email": user.email,
    }
