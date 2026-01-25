from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base
import uuid

# -----------------------------
# USERS (CUSTOMERS + ADMINS)
# -----------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="customer")  # admin | customer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# -----------------------------
# PRODUCTS
# -----------------------------
class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False)
    description = Column(String)
    price = Column(Numeric, nullable=False)
    currency = Column(String, default="LSL")
    category = Column(String)
    image_url = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# -----------------------------
# ORDERS (LINK TO USER LATER)
# -----------------------------
class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_reference = Column(String, unique=True, index=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    items = Column(JSONB)
    delivery_address = Column(JSONB)
    total_amount = Column(Numeric)
    currency = Column(String, default="LSL")
    payment_status = Column(String, default="pending")
    shipping_status = Column(String, default="pending")
    proof_file_url = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
from sqlalchemy import Enum
import enum

# -----------------------------
# ORDER STATUS ENUM
# -----------------------------
class OrderStatus(enum.Enum):
    created = "created"
    awaiting_payment = "awaiting_payment"
    payment_submitted = "payment_submitted"
    payment_verified = "payment_verified"
    payment_rejected = "payment_rejected"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


# -----------------------------
# PAYMENTS (MULTIPLE PER ORDER)
# -----------------------------
class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    amount = Column(Numeric, nullable=False)
    method = Column(String, nullable=False)  # bank_transfer, mobile_money, etc.

    proof_file_url = Column(String, nullable=True)

    status = Column(
        String,
        nullable=False,
        default="submitted"  # submitted | verified | rejected
    )

    admin_note = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
from sqlalchemy import Boolean, Text

# -----------------------------
# PAYMENT SETTINGS (ADMIN EDITABLE)
# -----------------------------
class PaymentSetting(Base):
    __tablename__ = "payment_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    method = Column(String, nullable=False)  
    # e.g. "bank_transfer", "mobile_money"

    provider_name = Column(String, nullable=False)
    account_name = Column(String, nullable=False)
    account_number = Column(String, nullable=False)

    instructions = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


