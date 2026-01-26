import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SqlEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


# =========================
# ENUMS
# =========================

class PaymentStatus(str, Enum):
    on_hold = "on_hold"
    payment_submitted = "payment_submitted"
    payment_received = "payment_received"
    rejected = "rejected"


class ShippingStatus(str, Enum):
    created = "created"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"


# =========================
# USER
# =========================

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="user")  # user | admin
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship(
        "Order",
        back_populates="user",
        cascade="all, delete-orphan",
    )


# =========================
# PRODUCT
# =========================

class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    img = Column(String, nullable=False)
    category = Column(String, nullable=False)
    rating = Column(Float, default=0)

    # INVENTORY
    stock = Column(Integer, nullable=False, default=0)
    in_stock = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)


# =========================
# ORDER
# =========================

class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    items = Column(JSONB, nullable=False)
    total_amount = Column(Float, nullable=False)

    # PAYMENT FLOW
    payment_status = Column(
        SqlEnum(PaymentStatus),
        default=PaymentStatus.on_hold,
        nullable=False,
    )

    # SHIPPING FLOW
    shipping_status = Column(
        SqlEnum(ShippingStatus),
        default=ShippingStatus.created,
        nullable=False,
    )

    tracking_number = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="orders")
    payment = relationship(
        "Payment",
        uselist=False,
        back_populates="order",
        cascade="all, delete-orphan",
    )


# =========================
# PAYMENT
# =========================

class Payment(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(
        String,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    proof_url = Column(String, nullable=True)

    status = Column(
        SqlEnum(PaymentStatus),
        default=PaymentStatus.on_hold,
        nullable=False,
    )

    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("Order", back_populates="payment")


# =========================
# PAYMENT SETTINGS (ADMIN)
# =========================

class PaymentSetting(Base):
    __tablename__ = "payment_settings"

    id = Column(Integer, primary_key=True, index=True)
    bank_name = Column(String, nullable=False)
    account_name = Column(String, nullable=False)
    account_number = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
