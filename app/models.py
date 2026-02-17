import uuid
import enum
from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean,
    DateTime, JSON, Enum, ForeignKey, Index,
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
    archived = "archived"    # NEW
    draft = "draft"          # NEW

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
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# =========================
# STORE (MULTI-STORE)  ← NEW
# =========================

class Store(Base):
    __tablename__ = "stores"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text)
    logo_url = Column(String)
    banner_url = Column(String)
    contact_email = Column(String)
    contact_phone = Column(String)
    address = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    products = relationship("Product", back_populates="store_ref", foreign_keys="Product.store_id")

Index("idx_stores_slug", Store.slug)
Index("idx_stores_active", Store.is_active)


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
    parent_asin = Column(String, index=True)
    price = Column(Float, nullable=False)
    compare_price = Column(Float)
    rating = Column(Float)
    rating_number = Column(Integer, default=0)
    sales = Column(Integer, default=0)
    category = Column(String, index=True)
    main_category = Column(String, index=True)
    categories = Column(JSON)
    specs = Column(JSON)
    details = Column(JSON)
    features = Column(JSON)
    stock = Column(Integer, default=0)
    in_stock = Column(Boolean, default=False)
    low_stock_threshold = Column(Integer, default=10)   # NEW
    store = Column(String, index=True)                  # kept for compat
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True)  # NEW FK
    status = Column(String, default="active", nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)   # NEW soft-delete
    deleted_at = Column(DateTime(timezone=True), nullable=True)   # NEW soft-delete
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.position")
    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")  # NEW
    store_ref = relationship("Store", back_populates="products", foreign_keys=[store_id])

Index("idx_products_status", Product.status)
Index("idx_products_price", Product.price)
Index("idx_products_created_at", Product.created_at)
Index("idx_products_rating", Product.rating)
Index("idx_products_parent_asin", Product.parent_asin)
Index("idx_products_is_deleted", Product.is_deleted)
Index("idx_products_store_id", Product.store_id)


# =========================
# PRODUCT IMAGES
# =========================

class ProductImage(Base):
    __tablename__ = "product_images"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    image_url = Column(String, nullable=False)
    position = Column(Integer, default=0)
    is_primary = Column(Boolean, default=False)   # NEW
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    product = relationship("Product", back_populates="images")


# =========================
# PRODUCT VARIANT  ← NEW
# =========================

class ProductVariant(Base):
    __tablename__ = "product_variants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)          # e.g. "Red / XL"
    sku = Column(String, index=True)
    attributes = Column(JSON, nullable=False, default=dict)  # {"color":"Red","size":"XL"}
    price = Column(Float, nullable=False)
    compare_price = Column(Float)
    stock = Column(Integer, default=0)
    in_stock = Column(Boolean, default=True)
    image_url = Column(String)
    is_active = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    product = relationship("Product", back_populates="variants")
    inventory_adjustments = relationship("InventoryAdjustment", back_populates="variant", foreign_keys="InventoryAdjustment.variant_id")

Index("idx_variants_product_id", ProductVariant.product_id)
Index("idx_variants_sku", ProductVariant.sku)
Index("idx_variants_active", ProductVariant.is_active)


# =========================
# INVENTORY ADJUSTMENT  ← NEW
# =========================

class InventoryAdjustment(Base):
    __tablename__ = "inventory_adjustments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=True, index=True)
    adjustment_type = Column(String, nullable=False, default="manual")  # manual/incoming/sale/return/correction
    quantity_before = Column(Integer, nullable=False)
    quantity_change = Column(Integer, nullable=False)   # +add / -remove
    quantity_after = Column(Integer, nullable=False)
    note = Column(Text)
    reference = Column(String)   # PO number, order ID, etc.
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    product = relationship("Product", foreign_keys=[product_id])
    variant = relationship("ProductVariant", back_populates="inventory_adjustments", foreign_keys=[variant_id])
    admin = relationship("User", foreign_keys=[admin_id])

Index("idx_inventory_adj_product", InventoryAdjustment.product_id)
Index("idx_inventory_adj_created", InventoryAdjustment.created_at)


# =========================
# AUDIT LOG  ← NEW
# =========================

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String, nullable=False, index=True)        # create/update/delete/archive/etc.
    entity_type = Column(String, nullable=False, index=True)   # product/order/store/variant
    entity_id = Column(String, nullable=True, index=True)
    before = Column(JSON)    # snapshot before change
    after = Column(JSON)     # snapshot after change
    meta = Column(JSON)      # IP, user-agent, bulk IDs, etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    admin = relationship("User", foreign_keys=[admin_id])

Index("idx_audit_logs_entity", AuditLog.entity_type, AuditLog.entity_id)
Index("idx_audit_logs_created", AuditLog.created_at)
Index("idx_audit_logs_admin", AuditLog.admin_id)


# =========================
# ORDER
# =========================

class Order(Base):
    __tablename__ = "orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    total_amount = Column(Float, nullable=False)
    status = Column(Enum(OrderStatus, name="order_status"), default=OrderStatus.pending, nullable=False)
    shipping_status = Column(Enum(ShippingStatus, name="shipping_status"), default=ShippingStatus.pending, nullable=False)
    shipping_address = Column(JSON)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    user = relationship("User", back_populates="orders")
    payments = relationship("Payment", back_populates="order", cascade="all, delete-orphan")


# =========================
# PAYMENT
# =========================

class Payment(Base):
    __tablename__ = "payments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    status = Column(Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.pending, nullable=False)
    method = Column(Enum(PaymentMethod, name="payment_method"), nullable=False)
    admin_notes = Column(Text)
    reviewed_by = Column(UUID(as_uuid=True))
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    order = relationship("Order", back_populates="payments")
    proof = relationship("PaymentProof", back_populates="payment", uselist=False, cascade="all, delete-orphan")


# =========================
# PAYMENT PROOF
# =========================

class PaymentProof(Base):
    __tablename__ = "payment_proofs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    file_url = Column(String, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    payment = relationship("Payment", back_populates="proof")


# =========================
# BANK SETTINGS
# =========================

class BankSettings(Base):
    __tablename__ = "bank_settings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bank_name = Column(String, nullable=False)
    account_name = Column(String, nullable=False)
    account_number = Column(String, nullable=False)
    branch = Column(String)
    swift_code = Column(String)
    mobile_money_provider = Column(String)
    mobile_money_number = Column(String)
    mobile_money_name = Column(String)
    qr_code_url = Column(String)
    instructions = Column(Text)
    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

Index("idx_bank_settings_active", BankSettings.is_active)


# =========================
# BULK UPLOAD LOG
# =========================

class BulkUpload(Base):
    __tablename__ = "bulk_uploads"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String, nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    total_rows = Column(Integer, default=0)
    successful_rows = Column(Integer, default=0)
    failed_rows = Column(Integer, default=0)
    status = Column(Enum(BulkUploadStatus, name="bulk_upload_status"), default=BulkUploadStatus.processing, nullable=False)
    errors = Column(JSON)
    summary = Column(JSON)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))

Index("idx_bulk_uploads_status", BulkUpload.status)
Index("idx_bulk_uploads_started", BulkUpload.started_at)