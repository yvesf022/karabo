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
