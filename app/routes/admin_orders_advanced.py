from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from app.database import get_db
from app.models import User, Order, OrderStatus, OrderNote, OrderReturn, Payment
from app.dependencies import require_admin

router = APIRouter(prefix="/admin/orders", tags=["admin-orders-advanced"])

class StatusOverridePayload(BaseModel):
    status: str
    reason: str

class RefundPayload(BaseModel):
    amount: float
    reason: str

class PartialRefundPayload(BaseModel):
    amount: float
    reason: str

class OrderNotePayload(BaseModel):
    note: str
    is_internal: bool = True

@router.delete("/{order_id}", status_code=status.HTTP_200_OK)
def hard_delete_order(order_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    db.delete(order)
    db.commit()
    return {"message": "Order permanently deleted"}

@router.patch("/{order_id}/status", status_code=status.HTTP_200_OK)
def force_status_override(order_id: str, payload: StatusOverridePayload, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        order.status = OrderStatus(payload.status)
    except ValueError:
        raise HTTPException(400, "Invalid status")
    if order.notes:
        order.notes += f"\n[Admin override by {admin.email}: {payload.reason}]"
    else:
        order.notes = f"[Admin override by {admin.email}: {payload.reason}]"
    db.commit()
    return {"message": "Status overridden", "new_status": order.status}

@router.post("/{order_id}/refund", status_code=status.HTTP_201_CREATED)
def process_refund(order_id: str, payload: RefundPayload, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.notes:
        order.notes += f"\n[Full refund processed: {payload.amount} by {admin.email}. Reason: {payload.reason}]"
    else:
        order.notes = f"[Full refund processed: {payload.amount} by {admin.email}. Reason: {payload.reason}]"
    order.status = OrderStatus.cancelled
    db.commit()
    return {"message": "Refund processed", "amount": payload.amount}

@router.post("/{order_id}/partial-refund", status_code=status.HTTP_201_CREATED)
def process_partial_refund(order_id: str, payload: PartialRefundPayload, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if payload.amount > order.total_amount:
        raise HTTPException(400, "Refund amount exceeds order total")
    if order.notes:
        order.notes += f"\n[Partial refund: {payload.amount} by {admin.email}. Reason: {payload.reason}]"
    else:
        order.notes = f"[Partial refund: {payload.amount} by {admin.email}. Reason: {payload.reason}]"
    db.commit()
    return {"message": "Partial refund processed", "amount": payload.amount}

@router.get("/{order_id}/notes", status_code=status.HTTP_200_OK)
def get_order_notes(order_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    notes = db.query(OrderNote).filter(OrderNote.order_id == order_id).order_by(OrderNote.created_at.desc()).all()
    return [{"id": str(n.id), "note": n.note, "is_internal": n.is_internal, "admin_id": str(n.admin_id) if n.admin_id else None, "created_at": n.created_at} for n in notes]

@router.post("/{order_id}/notes", status_code=status.HTTP_201_CREATED)
def create_order_note(order_id: str, payload: OrderNotePayload, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    note = OrderNote(order_id=order_id, admin_id=admin.id, note=payload.note, is_internal=payload.is_internal)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"message": "Note added", "note_id": str(note.id)}

@router.delete("/{order_id}/notes/{note_id}", status_code=status.HTTP_200_OK)
def delete_order_note(order_id: str, note_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    note = db.query(OrderNote).filter(OrderNote.id == note_id, OrderNote.order_id == order_id).first()
    if not note:
        raise HTTPException(404, "Note not found")
    db.delete(note)
    db.commit()
    return {"message": "Note deleted"}

@router.post("/{order_id}/restore", status_code=status.HTTP_200_OK)
def restore_order(order_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if hasattr(order, 'is_deleted') and order.is_deleted:
        order.is_deleted = False
        order.deleted_at = None
        db.commit()
        return {"message": "Order restored"}
    return {"message": "Order was not deleted"}
