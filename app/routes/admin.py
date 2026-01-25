from fastapi import APIRouter, Depends
from app.dependencies import require_admin
from app.models import User

router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------
# ADMIN: VERIFY ACCESS
# ---------------------------------
@router.get("/me")
def admin_me(admin: User = Depends(require_admin)):
    """
    Simple admin-only endpoint to confirm:
    - JWT is valid
    - User exists in DB
    - Role === admin
    """
    return {
        "id": str(admin.id),
        "email": admin.email,
        "role": admin.role,
        "message": "Admin access confirmed",
    }
