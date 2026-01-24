from fastapi import APIRouter, HTTPException
from app.security import verify_password, create_token
import os

router = APIRouter()

@router.post("/login")
def admin_login(data: dict):
    if data["email"] != os.getenv("ADMIN_EMAIL"):
        raise HTTPException(401)
    if not verify_password(data["password"], os.getenv("ADMIN_PASSWORD_HASH")):
        raise HTTPException(401)
    return {"token": create_token("admin", "admin")}
