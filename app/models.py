import uuid
import enum
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    JSON,
    Enum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


# =====================================================
# ENUMS (REQUIRED BY ROUTES)
# =====================================================
class OrderStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    cancelled = "cancelled"
    shipped = "shipped"
    completed = "completed"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    on_hold = "on_hold"
    paid = "paid"
    rejected = "rejected"


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

    title = Column(String, nullable=False)

    # Required by search & list queries
    short_description = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    sku = Column(String, nullable=True)
    brand = Column(String, nullable=True)

    price = Column(Float, nullable=False)
    compare_price = Column(Float, nullable=True)

    rating = Column(Float, nullable=True)
    sales = Column(Integer, default=0)

    main_image = Column(String, nullable=True)
    images = Column(JSON, nullable=True)

    category = Column(String, index=True, nullable=True)
    specs = Column(JSON, nullable=True)

    stock = Column(Integer, default=0)
    in_stock = Column(Boolean, default=True)

    status = Column(String, default="active")

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
# ORDER
# =====================================================
class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), nullable=False)

    total_amount = Column(Float, nullable=False)

    status = Column(
        Enum(OrderStatus, name="order_status"),
        default=OrderStatus.pending,
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


# =====================================================
# PAYMENT
# =====================================================
class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    order_id = Column(UUID(as_uuid=True), nullable=False)

    amount = Column(Float, nullable=False)

    status = Column(
        Enum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.pending,
        nullable=False,
    )

    method = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
