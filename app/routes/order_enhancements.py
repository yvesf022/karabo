from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from app.database import get_db
from app.models import User, Order, OrderStatus, OrderReturn, OrderTracking, Payment, PaymentStatus
from app.dependencies import get_current_user

router = APIRouter(prefix="/orders", tags=["order-enhancements"])

class CancelOrderPayload(BaseModel):
    reason: str

class ReturnOrderPayload(BaseModel):
    reason: str

class RefundRequestPayload(BaseModel):
    reason: str
    amount: float

@router.post("/{order_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_order(order_id: str, payload: CancelOrderPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status not in [OrderStatus.pending, OrderStatus.paid]:
        raise HTTPException(400, "Order cannot be cancelled")
    order.status = OrderStatus.cancelled
    if order.notes:
        order.notes += f"\n[User cancelled: {payload.reason}]"
    else:
        order.notes = f"[User cancelled: {payload.reason}]"
    db.commit()
    return {"message": "Order cancelled", "order_id": str(order.id)}

@router.post("/{order_id}/return", status_code=status.HTTP_201_CREATED)
def request_return(order_id: str, payload: ReturnOrderPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.completed:
        raise HTTPException(400, "Only completed orders can be returned")
    order_return = OrderReturn(order_id=order_id, user_id=user.id, reason=payload.reason, status="pending")
    db.add(order_return)
    db.commit()
    db.refresh(order_return)
    return {"message": "Return request submitted", "return_id": str(order_return.id)}

@router.post("/{order_id}/refund-request", status_code=status.HTTP_201_CREATED)
def request_refund(order_id: str, payload: RefundRequestPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.notes:
        order.notes += f"\n[Refund requested: {payload.reason}, Amount: {payload.amount}]"
    else:
        order.notes = f"[Refund requested: {payload.reason}, Amount: {payload.amount}]"
    db.commit()
    return {"message": "Refund request submitted", "order_id": str(order.id)}

@router.get("/{order_id}/tracking", status_code=status.HTTP_200_OK)
def get_tracking(order_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    tracking = db.query(OrderTracking).filter(OrderTracking.order_id == order_id).first()
    if not tracking:
        return {"message": "No tracking information available"}
    return {"carrier": tracking.carrier, "tracking_number": tracking.tracking_number, "tracking_url": tracking.tracking_url, "estimated_delivery": tracking.estimated_delivery, "actual_delivery": tracking.actual_delivery}

@router.get("/{order_id}/invoice", status_code=status.HTTP_200_OK)
def get_invoice(order_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    return {"order_id": str(order.id), "total_amount": order.total_amount, "status": order.status, "created_at": order.created_at, "message": "Invoice data (implement PDF generation as needed)"}
