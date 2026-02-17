from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from pydantic import BaseModel
from app.database import get_db
from app.models import User, Coupon, CouponUsage
from app.dependencies import get_current_user

router = APIRouter(prefix="/coupons", tags=["coupons"])

class ApplyCouponPayload(BaseModel):
    code: str
    order_total: float

@router.post("/apply", status_code=status.HTTP_200_OK)
def apply_coupon(payload: ApplyCouponPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    coupon = db.query(Coupon).filter(Coupon.code == payload.code, Coupon.is_active == True).first()
    if not coupon:
        raise HTTPException(404, "Coupon not found or inactive")
    now = datetime.utcnow()
    if now < coupon.valid_from or now > coupon.valid_until:
        raise HTTPException(400, "Coupon expired or not yet valid")
    if coupon.usage_limit and coupon.times_used >= coupon.usage_limit:
        raise HTTPException(400, "Coupon usage limit reached")
    user_usage = db.query(func.count(CouponUsage.id)).filter(CouponUsage.coupon_id == coupon.id, CouponUsage.user_id == user.id).scalar()
    if user_usage >= coupon.usage_per_user:
        raise HTTPException(400, "You have already used this coupon")
    if payload.order_total < coupon.min_purchase:
        raise HTTPException(400, f"Minimum purchase of {coupon.min_purchase} required")
    discount = 0
    if coupon.discount_type == "percentage":
        discount = payload.order_total * (coupon.discount_value / 100)
        if coupon.max_discount:
            discount = min(discount, coupon.max_discount)
    elif coupon.discount_type == "fixed":
        discount = coupon.discount_value
    return {"discount": round(discount, 2), "coupon_code": coupon.code, "description": coupon.description}

@router.delete("/remove", status_code=status.HTTP_200_OK)
def remove_coupon():
    return {"message": "Coupon removed"}

@router.get("/available", status_code=status.HTTP_200_OK)
def get_available_coupons(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    coupons = db.query(Coupon).filter(Coupon.is_active == True, Coupon.valid_from <= now, Coupon.valid_until >= now).all()
    return [{"code": c.code, "description": c.description, "discount_type": c.discount_type, "discount_value": c.discount_value} for c in coupons]

@router.get("/my", status_code=status.HTTP_200_OK)
def get_my_coupons(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    usages = db.query(CouponUsage).filter(CouponUsage.user_id == user.id).all()
    return [{"coupon_code": u.coupon.code, "discount_amount": u.discount_amount, "used_at": u.created_at} for u in usages if u.coupon]
