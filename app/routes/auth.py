from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Customer
from app.security import hash_password, verify_password, create_token

router = APIRouter()

@router.post("/auth/register")
def register(data: dict, db: Session = Depends(get_db)):
    if db.query(Customer).filter_by(email=data["email"]).first():
        raise HTTPException(400, "Email exists")
    user = Customer(
        email=data["email"],
        password_hash=hash_password(data["password"])
    )
    db.add(user)
    db.commit()
    return {"message": "registered"}

@router.post("/auth/login")
def login(data: dict, db: Session = Depends(get_db)):
    user = db.query(Customer).filter_by(email=data["email"]).first()
    if not user or not verify_password(data["password"], user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return {"token": create_token(str(user.id), "customer")}
