import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


# =====================================================
# USER
# =====================================================
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    full_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)

    role = Column(String, default="user")  # user | admin
    is_active = Column(Boolean, default=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


# =====================================================
# PRODUCT
# =====================================================
class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Core
    title = Column(String, nullable=False)

    # 🔥 REQUIRED BY SEARCH + LIST QUERIES
    short_description = Column(Text, nullable=True)

    description = Column(Text, nullable=True)

    sku = Column(String, nullable=True)
    brand = Column(String, nullable=True)

    # Pricing
    price = Column(Float, nullable=False)
    compare_price = Column(Float, nullable=True)

    # Merchandising
    rating = Column(Float, nullable=True)
    sales = Column(Integer, default=0)

    # Images
    main_image = Column(String, nullable=True)
    images = Column(JSON, nullable=True)

    # Categorization
    category = Column(String, index=True, nullable=True)
    specs = Column(JSON, nullable=True)

    # Inventory
    stock = Column(Integer, default=0)
    in_stock = Column(Boolean, default=True)

    # Lifecycle
    status = Column(String, default="active")  # active | draft | archived

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# =====================================================
# ORDER (BASIC – SAFE)
# =====================================================
class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), nullable=False)

    total_amount = Column(Float, nullable=False)

    payment_status = Column(String, default="pending")
    shipping_status = Column(String, default="pending")

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


# =====================================================
# PAYMENT (BASIC – SAFE)
# =====================================================
class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    order_id = Column(UUID(as_uuid=True), nullable=False)

    amount = Column(Float, nullable=False)
    method = Column(String, nullable=True)
    status = Column(String, default="pending")

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
