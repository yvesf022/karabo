from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import (
    get_current_user as _get_current_user,
    require_admin as _require_admin,
)


# =====================================================
# USER AUTH DEPENDENCY
# =====================================================

def get_current_user(
    request,
    db: Session = Depends(get_db),
) -> User:
    """
    Backward-compatible wrapper.
    Delegates all logic to app.security.get_current_user
    """
    return _get_current_user(request=request, db=db)


# =====================================================
# ADMIN AUTH DEPENDENCY
# =====================================================

def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """
    Backward-compatible admin guard.
    Delegates role enforcement to app.security.require_admin
    """
    return _require_admin(user)
