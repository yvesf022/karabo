from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel

from app.database import get_db
from app.models import User, Address
from app.dependencies import get_current_user

router = APIRouter(prefix="/users/me/addresses", tags=["addresses"])


# =====================================================
# Pydantic Schemas
# =====================================================

class AddressCreate(BaseModel):
    label: str
    full_name: str
    phone: str
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: str
    country: str


class AddressUpdate(BaseModel):
    label: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


# =====================================================
# USER: GET ALL MY ADDRESSES
# =====================================================
@router.get("", status_code=status.HTTP_200_OK)
def get_my_addresses(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all addresses for current user."""
    addresses = (
        db.query(Address)
        .filter(Address.user_id == user.id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
        .all()
    )

    return [
        {
            "id": str(addr.id),
            "label": addr.label,
            "full_name": addr.full_name,
            "phone": addr.phone,
            "address_line1": addr.address_line1,
            "address_line2": addr.address_line2,
            "city": addr.city,
            "state": addr.state,
            "postal_code": addr.postal_code,
            "country": addr.country,
            "is_default": addr.is_default,
            "created_at": addr.created_at,
        }
        for addr in addresses
    ]


# =====================================================
# USER: CREATE ADDRESS
# =====================================================
@router.post("", status_code=status.HTTP_201_CREATED)
def create_address(
    payload: AddressCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new address for current user."""
    # Check if this is the first address - make it default
    existing_count = db.query(Address).filter(Address.user_id == user.id).count()
    is_default = existing_count == 0

    address = Address(
        user_id=user.id,
        label=payload.label,
        full_name=payload.full_name,
        phone=payload.phone,
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
        country=payload.country,
        is_default=is_default,
    )

    db.add(address)
    db.commit()
    db.refresh(address)

    return {
        "id": str(address.id),
        "label": address.label,
        "full_name": address.full_name,
        "phone": address.phone,
        "address_line1": address.address_line1,
        "address_line2": address.address_line2,
        "city": address.city,
        "state": address.state,
        "postal_code": address.postal_code,
        "country": address.country,
        "is_default": address.is_default,
        "created_at": address.created_at,
    }


# =====================================================
# USER: UPDATE ADDRESS
# =====================================================
@router.patch("/{address_id}", status_code=status.HTTP_200_OK)
def update_address(
    address_id: str,
    payload: AddressUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update an existing address."""
    address = (
        db.query(Address)
        .filter(Address.id == address_id, Address.user_id == user.id)
        .first()
    )

    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    updated_fields = payload.dict(exclude_unset=True)

    if not updated_fields:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    for field, value in updated_fields.items():
        setattr(address, field, value)

    db.commit()
    db.refresh(address)

    return {
        "message": "Address updated successfully",
        "id": str(address.id),
        "label": address.label,
        "full_name": address.full_name,
        "phone": address.phone,
        "address_line1": address.address_line1,
        "address_line2": address.address_line2,
        "city": address.city,
        "state": address.state,
        "postal_code": address.postal_code,
        "country": address.country,
        "is_default": address.is_default,
    }


# =====================================================
# USER: DELETE ADDRESS
# =====================================================
@router.delete("/{address_id}", status_code=status.HTTP_200_OK)
def delete_address(
    address_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete an address."""
    address = (
        db.query(Address)
        .filter(Address.id == address_id, Address.user_id == user.id)
        .first()
    )

    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    was_default = address.is_default

    db.delete(address)
    db.commit()

    # If deleted address was default, make another one default
    if was_default:
        new_default = (
            db.query(Address)
            .filter(Address.user_id == user.id)
            .first()
        )
        if new_default:
            new_default.is_default = True
            db.commit()

    return {"message": "Address deleted successfully"}


# =====================================================
# USER: SET DEFAULT ADDRESS
# =====================================================
@router.post("/{address_id}/set-default", status_code=status.HTTP_200_OK)
def set_default_address(
    address_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Set an address as the default."""
    address = (
        db.query(Address)
        .filter(Address.id == address_id, Address.user_id == user.id)
        .first()
    )

    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    # Remove default from all other addresses
    db.query(Address).filter(
        Address.user_id == user.id,
        Address.id != address_id
    ).update({"is_default": False})

    address.is_default = True
    db.commit()
    db.refresh(address)

    return {
        "message": "Default address updated",
        "address_id": str(address.id),
    }
