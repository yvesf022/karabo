from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base
import uuid

class Customer(Base):
    __tablename__ = "customers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Product(Base):
    __tablename__ = "products"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String)
    description = Column(String)
    price = Column(Numeric)
    currency = Column(String, default="LSL")
    category = Column(String)
    image_url = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Order(Base):
    __tablename__ = "orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_reference = Column(String, unique=True, index=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"))
    items = Column(JSONB)
    delivery_address = Column(JSONB)
    total_amount = Column(Numeric)
    currency = Column(String, default="LSL")
    payment_status = Column(String, default="pending_payment")
    shipping_status = Column(String, default="pending")
    proof_file_url = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
