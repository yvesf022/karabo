from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import verify_password, hash_password, create_token

router = APIRouter(prefix="/api/auth", tags=["Auth"])


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
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account disabled",
        )

    token = create_token(user.id, user.role)

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
    }


# =========================
# REGISTER
# =========================
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
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"message": "Account created successfully"}
