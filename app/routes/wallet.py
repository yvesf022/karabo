from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import User, Wallet, WalletTransaction
from app.dependencies import get_current_user

router = APIRouter(prefix="/wallet", tags=["wallet"])

class RedeemPayload(BaseModel):
    points: int

def get_or_create_wallet(db: Session, user: User) -> Wallet:
    wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
    if not wallet:
        wallet = Wallet(user_id=user.id, balance=0, loyalty_points=0)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
    return wallet

@router.get("", status_code=status.HTTP_200_OK)
def get_wallet(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wallet = get_or_create_wallet(db, user)
    return {"wallet_id": str(wallet.id), "balance": wallet.balance, "loyalty_points": wallet.loyalty_points, "updated_at": wallet.updated_at}

@router.get("/transactions", status_code=status.HTTP_200_OK)
def get_wallet_transactions(limit: int = 50, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wallet = get_or_create_wallet(db, user)
    txns = db.query(WalletTransaction).filter(WalletTransaction.wallet_id == wallet.id).order_by(WalletTransaction.created_at.desc()).limit(limit).all()
    return [{"id": str(t.id), "type": t.type, "amount": t.amount, "points": t.points, "balance_after": t.balance_after, "description": t.description, "created_at": t.created_at} for t in txns]

@router.post("/redeem", status_code=status.HTTP_200_OK)
def redeem_points(payload: RedeemPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wallet = get_or_create_wallet(db, user)
    if wallet.loyalty_points < payload.points:
        raise HTTPException(400, "Insufficient points")
    conversion_rate = 0.01
    credit_amount = payload.points * conversion_rate
    wallet.loyalty_points -= payload.points
    wallet.balance += credit_amount
    txn = WalletTransaction(wallet_id=wallet.id, type="credit", amount=credit_amount, points=-payload.points, balance_before=wallet.balance - credit_amount, balance_after=wallet.balance, description=f"Redeemed {payload.points} points")
    db.add(txn)
    db.commit()
    return {"message": "Points redeemed", "credited_amount": credit_amount, "new_balance": wallet.balance, "remaining_points": wallet.loyalty_points}
