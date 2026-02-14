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
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


# =========================
# ENUMS
# =========================

class OrderStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    cancelled = "cancelled"
    shipped = "shipped"
    completed = "completed"


class ShippingStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"
    returned = "returned"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    on_hold = "on_hold"
    paid = "paid"
    rejected = "rejected"


class PaymentMethod(str, enum.Enum):
    card = "card"
    cash = "cash"
    mobile_money = "mobile_money"
    bank_transfer = "bank_transfer"


class ProductStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    discontinued = "discontinued"


class BulkUploadStatus(str, enum.Enum):
    processing = "processing"
    completed = "completed"
    failed = "failed"
    partial = "partial"


# =========================
# USER
# =========================

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)

    full_name = Column(String)
    phone = Column(String)

    avatar_url = Column(String)

    role = Column(String, default="user", nullable=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    orders = relationship(
        "Order",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# =========================
# PRODUCT
# =========================

class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    title = Column(String, nullable=False)
    short_description = Column(Text)
    description = Column(Text)

    sku = Column(String, index=True)
    brand = Column(String, index=True)
    parent_asin = Column(String, index=True)  # NEW: For Amazon compatibility

    price = Column(Float, nullable=False)
    compare_price = Column(Float)

    rating = Column(Float)
    rating_number = Column(Integer, default=0)  # NEW: Number of ratings
    sales = Column(Integer, default=0)

    category = Column(String, index=True)
    main_category = Column(String, index=True)  # NEW: Main category
    categories = Column(JSON)  # NEW: All categories
    specs = Column(JSON)
    details = Column(JSON)  # NEW: Product details
    features = Column(JSON)  # NEW: Product features

    stock = Column(Integer, default=0)
    in_stock = Column(Boolean, default=False)

    store = Column(String, index=True)  # NEW: Store/brand name

    status = Column(
        String,
        default="active",
        nullable=False,
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    images = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.position",
    )


Index("idx_products_status", Product.status)
Index("idx_products_price", Product.price)
Index("idx_products_created_at", Product.created_at)
Index("idx_products_rating", Product.rating)
Index("idx_products_parent_asin", Product.parent_asin)


# =========================
# PRODUCT IMAGES
# =========================

class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    image_url = Column(String, nullable=False)
    position = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    product = relationship("Product", back_populates="images")


# =========================
# ORDER
# =========================

class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    total_amount = Column(Float, nullable=False)

    status = Column(
        Enum(OrderStatus, name="order_status"),
        default=OrderStatus.pending,
        nullable=False,
    )

    shipping_status = Column(
        Enum(ShippingStatus, name="shipping_status"),
        default=ShippingStatus.pending,
        nullable=False,
    )

    shipping_address = Column(JSON)  # NEW: Store shipping details
    notes = Column(Text)  # NEW: Order notes

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="orders")
    payments = relationship(
        "Payment",
        back_populates="order",
        cascade="all, delete-orphan",
    )


# =========================
# PAYMENT
# =========================

class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount = Column(Float, nullable=False)

    status = Column(
        Enum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.pending,
        nullable=False,
    )

    method = Column(
        Enum(PaymentMethod, name="payment_method"),
        nullable=False,
    )

    admin_notes = Column(Text)  # NEW: Admin review notes
    reviewed_by = Column(UUID(as_uuid=True))  # NEW: Admin who reviewed
    reviewed_at = Column(DateTime(timezone=True))  # NEW: Review timestamp

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="payments")
    proof = relationship(
        "PaymentProof",
        back_populates="payment",
        uselist=False,
        cascade="all, delete-orphan",
    )


# =========================
# PAYMENT PROOF
# =========================

class PaymentProof(Base):
    __tablename__ = "payment_proofs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    payment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_url = Column(String, nullable=False)

    uploaded_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    payment = relationship("Payment", back_populates="proof")


# =========================
# BANK SETTINGS (NEW)
# =========================

class BankSettings(Base):
    """Admin-configured bank account details for manual payments"""
    __tablename__ = "bank_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    bank_name = Column(String, nullable=False)
    account_name = Column(String, nullable=False)
    account_number = Column(String, nullable=False)
    branch = Column(String)
    swift_code = Column(String)

    mobile_money_provider = Column(String)  # e.g., M-Pesa, MTN
    mobile_money_number = Column(String)
    mobile_money_name = Column(String)

    qr_code_url = Column(String)  # Payment QR code image
    instructions = Column(Text)  # Payment instructions for customers

    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


Index("idx_bank_settings_active", BankSettings.is_active)


# =========================
# BULK UPLOAD LOG (NEW)
# =========================

class BulkUpload(Base):
    """Track CSV bulk upload operations"""
    __tablename__ = "bulk_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    filename = Column(String, nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    total_rows = Column(Integer, default=0)
    successful_rows = Column(Integer, default=0)
    failed_rows = Column(Integer, default=0)

    status = Column(
        Enum(BulkUploadStatus, name="bulk_upload_status"),
        default=BulkUploadStatus.processing,
        nullable=False,
    )

    errors = Column(JSON)  # Store error details
    summary = Column(JSON)  # Upload summary stats

    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))


Index("idx_bulk_uploads_status", BulkUpload.status)
Index("idx_bulk_uploads_started", BulkUpload.started_at)