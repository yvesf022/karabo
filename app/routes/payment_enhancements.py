from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import User, Payment, PaymentStatus, PaymentProof
from app.dependencies import get_current_user
from app.uploads.service import handle_upload

router = APIRouter(prefix="/payments", tags=["payment-enhancements"])

class CancelPaymentPayload(BaseModel):
    reason: str

@router.post("/{payment_id}/resubmit-proof", status_code=status.HTTP_200_OK)
def resubmit_payment_proof(payment_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment or payment.order.user_id != user.id:
        raise HTTPException(404, "Payment not found")
    if payment.status not in [PaymentStatus.rejected, PaymentStatus.pending]:
        raise HTTPException(400, "Cannot resubmit proof for this payment")
    proof_url = handle_upload(file=file, folder="payment_proofs", owner_id=str(user.id))
    if payment.proof:
        payment.proof.file_url = proof_url
    else:
        proof = PaymentProof(payment_id=payment_id, file_url=proof_url)
        db.add(proof)
    payment.status = PaymentStatus.pending
    db.commit()
    return {"message": "Proof resubmitted", "proof_url": proof_url}

@router.post("/{payment_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_payment(payment_id: str, payload: CancelPaymentPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment or payment.order.user_id != user.id:
        raise HTTPException(404, "Payment not found")
    if payment.status != PaymentStatus.pending:
        raise HTTPException(400, "Only pending payments can be cancelled")
    payment.status = PaymentStatus.rejected
    if payment.admin_notes:
        payment.admin_notes += f"\n[User cancelled: {payload.reason}]"
    else:
        payment.admin_notes = f"[User cancelled: {payload.reason}]"
    db.commit()
    return {"message": "Payment cancelled"}

@router.post("/{order_id}/retry", status_code=status.HTTP_201_CREATED)
def retry_payment(order_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import Order
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    return {"message": "Payment retry initiated", "order_id": str(order_id)}

@router.get("/{payment_id}/status-history", status_code=status.HTTP_200_OK)
def get_payment_status_history(payment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import PaymentStatusHistory
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment or payment.order.user_id != user.id:
        raise HTTPException(404, "Payment not found")
    history = db.query(PaymentStatusHistory).filter(PaymentStatusHistory.payment_id == payment_id).order_by(PaymentStatusHistory.created_at.desc()).all()
    return [{"old_status": h.old_status, "new_status": h.new_status, "created_at": h.created_at} for h in history]
