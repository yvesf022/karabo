from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.dependencies import require_admin

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


# =====================================================
# ADMIN: LIST USERS
# =====================================================
@router.get("", dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at.desc()).all()

    return [
        {
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "phone": u.phone,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at,
        }
        for u in users
    ]


# =====================================================
# ADMIN: DISABLE USER
# =====================================================
@router.post("/{user_id}/disable", dependencies=[Depends(require_admin)])
def disable_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()

    return {"id": str(user.id), "status": "disabled"}


# =====================================================
# ADMIN: ENABLE USER
# =====================================================
@router.post("/{user_id}/enable", dependencies=[Depends(require_admin)])
def enable_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = True
    db.commit()

    return {"id": str(user.id), "status": "enabled"}


# =====================================================
# ADMIN: PROMOTE / DEMOTE
# =====================================================
@router.post("/{user_id}/role", dependencies=[Depends(require_admin)])
def change_role(
    user_id: str,
    role: str,
    db: Session = Depends(get_db),
):
    if role not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role
    db.commit()

    return {"id": str(user.id), "role": user.role}
