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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
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


class SupportStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"


# =========================
# USER
# =========================

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    full_name = Column(String)
    phone = Column(String)
    avatar_url = Column(String)

    role = Column(String, default="user")
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    support_tickets = relationship("SupportTicket", back_populates="user", cascade="all, delete-orphan")
    wishlist_items = relationship("WishlistItem", back_populates="user", cascade="all, delete-orphan")


# =========================
# ADDRESS
# =========================

class Address(Base):
    __tablename__ = "addresses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    full_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)

    address_line_1 = Column(String, nullable=False)
    address_line_2 = Column(String)
    city = Column(String, nullable=False)
    state = Column(String, nullable=False)
    postal_code = Column(String, nullable=False)
    country = Column(String, nullable=False)

    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="addresses")
    orders = relationship("Order", back_populates="address")


# =========================
# PRODUCT
# =========================

class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    img = Column(String, nullable=False)
    category = Column(String, nullable=False)
    rating = Column(Float, default=0)

    stock = Column(Integer, default=0)
    in_stock = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    wishlist_users = relationship("WishlistItem", back_populates="product", cascade="all, delete-orphan")


# =========================
# WISHLIST
# =========================

class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uix_user_product"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="wishlist_items")
    product = relationship("Product", back_populates="wishlist_users")


# =========================
# ORDER
# =========================

class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    address_id = Column(UUID(as_uuid=True), ForeignKey("addresses.id", ondelete="SET NULL"))

    items = Column(JSONB, nullable=False)
    total_amount = Column(Float, nullable=False)

    payment_status = Column(SqlEnum(PaymentStatus), default=PaymentStatus.on_hold, nullable=False)
    shipping_status = Column(SqlEnum(ShippingStatus), default=ShippingStatus.created, nullable=False)

    tracking_number = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="orders")
    address = relationship("Address", back_populates="orders")
    payment = relationship("Payment", uselist=False, back_populates="order", cascade="all, delete-orphan")


# =========================
# PAYMENT
# =========================

class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False)

    proof_url = Column(String)
    status = Column(SqlEnum(PaymentStatus), default=PaymentStatus.on_hold, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("Order", back_populates="payment")


# =========================
# SUPPORT
# =========================

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    subject = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    status = Column(SqlEnum(SupportStatus), default=SupportStatus.open, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="support_tickets")


# =========================
# PAYMENT SETTINGS
# =========================

class PaymentSetting(Base):
    __tablename__ = "payment_settings"

    id = Column(Integer, primary_key=True, index=True)
    bank_name = Column(String, nullable=False)
    account_name = Column(String, nullable=False)
    account_number = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
