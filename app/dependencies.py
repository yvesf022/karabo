from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import decode_access_token


# =====================================================
# USER AUTH DEPENDENCY
# =====================================================

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Resolves the currently authenticated user from the access token cookie.
    """

    token_data = decode_access_token(request)

    user = (
        db.query(User)
        .filter(User.id == token_data.user_id, User.is_active == True)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    return user


# =====================================================
# ADMIN AUTH DEPENDENCY
# =====================================================

def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """
    Ensures the current user is an admin.
    DB is the source of truth.
    """

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return user
