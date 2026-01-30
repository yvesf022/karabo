from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models import User
from app.security import verify_password, create_token, decode_token

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


class AdminLoginPayload(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def admin_login(
    payload: AdminLoginPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access denied")

    token = create_token(user.id, "admin")

    response.set_cookie(
        key="admin_access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",                     # ✅ FIXED
        max_age=60 * 60 * 8,          # 8 hours
    )

    return {
        "id": str(user.id),
        "email": user.email,
        "role": "admin",
    }


@router.post("/logout")
def admin_logout(response: Response):
    response.delete_cookie(
        key="admin_access_token",
        path="/",                     # ✅ FIXED
    )
    return {"message": "Admin logged out"}


@router.get("/me")
def admin_me(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("admin_access_token")

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    payload = decode_token(token)
    if not payload or payload.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    admin = db.query(User).filter(User.id == payload["sub"]).first()
    if not admin or admin.role != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return {
        "id": str(admin.id),
        "email": admin.email,
        "role": "admin",
    }
