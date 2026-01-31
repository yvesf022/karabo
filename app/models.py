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
    Text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


# =====================================================
# ENUMS
# =====================================================

class UserRole(str, Enum):
    user = "user"
    admin = "admin"


class ProductStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class OrderStatus(str, Enum):
    created = "created"
    awaiting_payment = "awaiting_payment"
    payment_under_review = "payment_under_review"
    paid = "paid"
    cancelled = "cancelled"


class PaymentStatus(str, Enum):
    initiated = "initiated"
    proof_submitted = "proof_submitted"
    approved = "approved"
    rejected = "rejected"
    refunded = "refunded"


class ShippingStatus(str, Enum):
    created = "created"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"


class PaymentMethod(str, Enum):
    bank_transfer = "bank_transfer"


# =====================================================
# USER
# =====================================================

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    full_name = Column(String)
    phone = Column(String)
    avatar_url = Column(String)

    role = Column(SqlEnum(UserRole), default=UserRole.user)
    is_active = Column(Boolean, default=True)

    # 🔑 EMAIL VERIFICATION
    is_verified = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship(
        "Order",
        back_populates="user",
        cascade="all, delete-orphan"
    )


# =====================================================
# PRODUCT
# =====================================================

class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    title = Column(String, nullable=False)
    short_description = Column(String)
    description = Column(Text)

    sku = Column(String, unique=True, index=True, nullable=False)
    price = Column(Float, nullable=False)
    compare_price = Column(Float)

    brand = Column(String, index=True)
    rating = Column(Float, default=0.0)
    sales = Column(Integer, default=0)

    main_image = Column(String, nullable=False)
    images = Column(JSONB, default=list)

    category = Column(String, nullable=False)
    specs = Column(JSONB, default=dict)

    stock = Column(Integer, default=0)
    in_stock = Column(Boolean, default=False)

    status = Column(SqlEnum(ProductStatus), default=ProductStatus.active)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# =====================================================
# ORDER
# =====================================================

class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    items = Column(JSONB, nullable=False)
    total_amount = Column(Float, nullable=False)

    order_status = Column(SqlEnum(OrderStatus), default=OrderStatus.created)
    shipping_status = Column(SqlEnum(ShippingStatus), default=ShippingStatus.created)

    tracking_number = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="orders")
    payment = relationship(
        "Payment",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
    )


# =====================================================
# PAYMENT
# =====================================================

class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    method = Column(SqlEnum(PaymentMethod), nullable=False)
    amount = Column(Float, nullable=False)

    proof_url = Column(String)

    status = Column(SqlEnum(PaymentStatus), default=PaymentStatus.initiated)

    reviewed_by_admin = Column(Boolean, default=False)
    reviewed_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("Order", back_populates="payment")
