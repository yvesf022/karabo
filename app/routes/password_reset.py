from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
import secrets

from app.database import get_db
from app.models import User
from app.passwords import hash_password

router = APIRouter(prefix="/auth/password", tags=["password-reset"])

# In-memory token store (OK for now; Redis later)
RESET_TOKENS: dict[str, dict] = {}

TOKEN_EXPIRY_MINUTES = 15


# =========================
# SCHEMAS
# =========================

class ResetRequest(BaseModel):
    email: EmailStr


class ResetConfirm(BaseModel):
    token: str
    new_password: str


# =========================
# REQUEST RESET
# =========================

@router.post("/request")
def request_reset(payload: ResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        # Do NOT reveal account existence
        return {"detail": "If account exists, reset instructions sent"}

    token = secrets.token_urlsafe(32)
    RESET_TOKENS[token] = {
        "user_id": user.id,
        "expires": datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRY_MINUTES),
    }

    # TODO: send email instead of print
    print("PASSWORD RESET TOKEN:", token)

    return {"detail": "If account exists, reset instructions sent"}


# =========================
# CONFIRM RESET
# =========================

@router.post("/confirm")
def confirm_reset(payload: ResetConfirm, db: Session = Depends(get_db)):
    entry = RESET_TOKENS.get(payload.token)
    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    if entry["expires"] < datetime.utcnow():
        RESET_TOKENS.pop(payload.token, None)
        raise HTTPException(status_code=400, detail="Token expired")

    user = db.query(User).filter(User.id == entry["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # ✅ CORRECT FIELD NAME
    user.hashed_password = hash_password(payload.new_password)
    db.commit()

    RESET_TOKENS.pop(payload.token, None)

    return {"detail": "Password reset successful"}
