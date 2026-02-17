from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.database import get_db
from app.models import User, AuditLog, UserSession
from app.dependencies import require_admin

router = APIRouter(prefix="/admin", tags=["admin-users-advanced"])

class ForcePasswordResetPayload(BaseModel):
    reason: str

@router.delete("/users/{user_id}", status_code=status.HTTP_200_OK)
def hard_delete_user(user_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.is_admin:
        raise HTTPException(400, "Cannot delete admin users")
    db.delete(user)
    db.commit()
    return {"message": "User permanently deleted"}

@router.post("/users/{user_id}/force-password-reset", status_code=status.HTTP_200_OK)
def force_password_reset(user_id: str, payload: ForcePasswordResetPayload, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    log = AuditLog(admin_id=admin.id, action="force_password_reset", entity_type="user", entity_id=str(user_id), meta={"reason": payload.reason, "admin_email": admin.email})
    db.add(log)
    db.commit()
    return {"message": "Password reset initiated", "user_id": str(user_id)}

@router.get("/users/{user_id}/activity", status_code=status.HTTP_200_OK)
def get_user_activity(user_id: str, limit: int = 50, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    logs = db.query(AuditLog).filter(AuditLog.entity_type == "user", AuditLog.entity_id == str(user_id)).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{"id": str(l.id), "action": l.action, "created_at": l.created_at, "admin_email": l.admin.email if l.admin else None} for l in logs]

@router.get("/sessions", status_code=status.HTTP_200_OK)
def get_all_sessions(active_only: bool = True, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    query = db.query(UserSession)
    if active_only:
        query = query.filter(UserSession.expires_at > datetime.utcnow())
    sessions = query.order_by(UserSession.last_activity.desc()).limit(100).all()
    return [{"id": str(s.id), "user_id": str(s.user_id), "ip_address": s.ip_address, "device_type": s.device_type, "last_activity": s.last_activity, "expires_at": s.expires_at} for s in sessions]

@router.delete("/sessions/{session_id}", status_code=status.HTTP_200_OK)
def delete_session(session_id: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    db.delete(session)
    db.commit()
    return {"message": "Session terminated"}
