# =====================================================
# ADD THESE MODELS TO YOUR EXISTING models.py
# =====================================================

# =========================
# ADDRESS
# =========================

class Address(Base):
    __tablename__ = "addresses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String, nullable=False)  # "Home", "Work", etc.
    full_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    address_line1 = Column(String, nullable=False)
    address_line2 = Column(String)
    city = Column(String, nullable=False)
    state = Column(String)
    postal_code = Column(String, nullable=False)
    country = Column(String, nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    user = relationship("User", back_populates="addresses")

Index("idx_addresses_user_id", Address.user_id)
Index("idx_addresses_is_default", Address.is_default)


# =========================
# CART
# =========================

class Cart(Base):
    __tablename__ = "carts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    user = relationship("User", back_populates="cart")
    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")

Index("idx_carts_user_id", Cart.user_id)


class CartItem(Base):
    __tablename__ = "cart_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cart_id = Column(UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True)
    quantity = Column(Integer, nullable=False, default=1)
    price = Column(Float, nullable=False)  # Price snapshot at time of adding
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    cart = relationship("Cart", back_populates="items")
    product = relationship("Product")
    variant = relationship("ProductVariant")

Index("idx_cart_items_cart_id", CartItem.cart_id)
Index("idx_cart_items_product_id", CartItem.product_id)


# =========================
# WISHLIST
# =========================

class Wishlist(Base):
    __tablename__ = "wishlists"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="wishlist")
    product = relationship("Product")

Index("idx_wishlists_user_id", Wishlist.user_id)
Index("idx_wishlists_user_product", Wishlist.user_id, Wishlist.product_id, unique=True)


# =========================
# REVIEWS
# =========================

class Review(Base):
    __tablename__ = "reviews"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    title = Column(String)
    comment = Column(Text)
    is_verified_purchase = Column(Boolean, default=False)
    helpful_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    product = relationship("Product", back_populates="reviews")
    user = relationship("User", back_populates="reviews")
    votes = relationship("ReviewVote", back_populates="review", cascade="all, delete-orphan")

Index("idx_reviews_product_id", Review.product_id)
Index("idx_reviews_user_id", Review.user_id)
Index("idx_reviews_rating", Review.rating)


class ReviewVote(Base):
    __tablename__ = "review_votes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id = Column(UUID(as_uuid=True), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    is_helpful = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    review = relationship("Review", back_populates="votes")
    user = relationship("User")

Index("idx_review_votes_review_user", ReviewVote.review_id, ReviewVote.user_id, unique=True)


# =========================
# PRODUCT Q&A
# =========================

class ProductQuestion(Base):
    __tablename__ = "product_questions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    product = relationship("Product", back_populates="questions")
    user = relationship("User")
    answers = relationship("ProductAnswer", back_populates="question", cascade="all, delete-orphan")

Index("idx_product_questions_product_id", ProductQuestion.product_id)


class ProductAnswer(Base):
    __tablename__ = "product_answers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id = Column(UUID(as_uuid=True), ForeignKey("product_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    answer = Column(Text, nullable=False)
    is_seller = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    question = relationship("ProductQuestion", back_populates="answers")
    user = relationship("User")

Index("idx_product_answers_question_id", ProductAnswer.question_id)


# =========================
# CATEGORIES & BRANDS
# =========================

class Category(Base):
    __tablename__ = "categories"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)
    image_url = Column(String)
    is_active = Column(Boolean, default=True)
    position = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    parent = relationship("Category", remote_side=[id], backref="subcategories")

Index("idx_categories_slug", Category.slug)
Index("idx_categories_parent_id", Category.parent_id)


class Brand(Base):
    __tablename__ = "brands"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text)
    logo_url = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Index("idx_brands_slug", Brand.slug)


# =========================
# ORDER ENHANCEMENTS
# =========================

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True)
    product_title = Column(String, nullable=False)  # Snapshot
    variant_title = Column(String)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)  # Price at time of order
    subtotal = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    order = relationship("Order", back_populates="items")
    product = relationship("Product")
    variant = relationship("ProductVariant")

Index("idx_order_items_order_id", OrderItem.order_id)


class OrderReturn(Base):
    __tablename__ = "order_returns"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    status = Column(String, default="pending", nullable=False)  # pending/approved/rejected/completed
    admin_notes = Column(Text)
    refund_amount = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    order = relationship("Order", back_populates="returns")
    user = relationship("User")

Index("idx_order_returns_order_id", OrderReturn.order_id)
Index("idx_order_returns_status", OrderReturn.status)


class OrderTracking(Base):
    __tablename__ = "order_tracking"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    carrier = Column(String)
    tracking_number = Column(String)
    tracking_url = Column(String)
    estimated_delivery = Column(DateTime(timezone=True))
    actual_delivery = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    order = relationship("Order", back_populates="tracking", uselist=False)

Index("idx_order_tracking_order_id", OrderTracking.order_id)


class OrderNote(Base):
    __tablename__ = "order_notes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=True)  # Internal notes vs customer-visible
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    order = relationship("Order", back_populates="admin_notes")
    admin = relationship("User")

Index("idx_order_notes_order_id", OrderNote.order_id)


# =========================
# PAYMENT ENHANCEMENTS
# =========================

class PaymentStatusHistory(Base):
    __tablename__ = "payment_status_history"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(String)
    new_status = Column(String, nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    payment = relationship("Payment", back_populates="status_history")
    admin = relationship("User")

Index("idx_payment_history_payment_id", PaymentStatusHistory.payment_id)


# =========================
# NOTIFICATIONS
# =========================

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String, nullable=False)  # order_update/payment_status/promotion/etc
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    link = Column(String)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="notifications")

Index("idx_notifications_user_id", Notification.user_id)
Index("idx_notifications_is_read", Notification.is_read)
Index("idx_notifications_created_at", Notification.created_at)


# =========================
# RECENTLY VIEWED
# =========================

class RecentlyViewed(Base):
    __tablename__ = "recently_viewed"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    viewed_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    user = relationship("User")
    product = relationship("Product")

Index("idx_recently_viewed_user_id", RecentlyViewed.user_id)
Index("idx_recently_viewed_viewed_at", RecentlyViewed.viewed_at)
Index("idx_recently_viewed_user_product", RecentlyViewed.user_id, RecentlyViewed.product_id, unique=True)


# =========================
# COUPONS
# =========================

class Coupon(Base):
    __tablename__ = "coupons"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text)
    discount_type = Column(String, nullable=False)  # percentage/fixed/free_shipping
    discount_value = Column(Float, nullable=False)
    min_purchase = Column(Float, default=0)
    max_discount = Column(Float)  # For percentage discounts
    usage_limit = Column(Integer)  # Total times it can be used
    usage_per_user = Column(Integer, default=1)
    times_used = Column(Integer, default=0)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    usages = relationship("CouponUsage", back_populates="coupon", cascade="all, delete-orphan")

Index("idx_coupons_code", Coupon.code)
Index("idx_coupons_valid_from", Coupon.valid_from)
Index("idx_coupons_valid_until", Coupon.valid_until)


class CouponUsage(Base):
    __tablename__ = "coupon_usages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    coupon_id = Column(UUID(as_uuid=True), ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    discount_amount = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    coupon = relationship("Coupon", back_populates="usages")
    user = relationship("User")
    order = relationship("Order")

Index("idx_coupon_usages_coupon_id", CouponUsage.coupon_id)
Index("idx_coupon_usages_user_id", CouponUsage.user_id)


# =========================
# WALLET (OPTIONAL)
# =========================

class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    balance = Column(Float, default=0, nullable=False)
    loyalty_points = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    user = relationship("User", back_populates="wallet", uselist=False)
    transactions = relationship("WalletTransaction", back_populates="wallet", cascade="all, delete-orphan")

Index("idx_wallets_user_id", Wallet.user_id)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String, nullable=False)  # credit/debit/refund/purchase
    amount = Column(Float, nullable=False)
    points = Column(Integer, default=0)
    balance_before = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    description = Column(Text)
    reference = Column(String)  # Order ID, refund ID, etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    wallet = relationship("Wallet", back_populates="transactions")

Index("idx_wallet_transactions_wallet_id", WalletTransaction.wallet_id)
Index("idx_wallet_transactions_created_at", WalletTransaction.created_at)


# =========================
# USER SESSIONS (For session management)
# =========================

class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String, nullable=False, unique=True, index=True)
    ip_address = Column(String)
    user_agent = Column(String)
    device_type = Column(String)
    last_activity = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User")

Index("idx_user_sessions_user_id", UserSession.user_id)
Index("idx_user_sessions_token", UserSession.token)
Index("idx_user_sessions_expires_at", UserSession.expires_at)


# =====================================================
# UPDATE EXISTING MODELS WITH RELATIONSHIPS
# =====================================================
# Add these to your existing User model:
# addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
# cart = relationship("Cart", back_populates="user", uselist=False, cascade="all, delete-orphan")
# wishlist = relationship("Wishlist", back_populates="user", cascade="all, delete-orphan")
# reviews = relationship("Review", back_populates="user", cascade="all, delete-orphan")
# notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
# wallet = relationship("Wallet", back_populates="user", uselist=False, cascade="all, delete-orphan")

# Add these to your existing Order model:
# items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
# returns = relationship("OrderReturn", back_populates="order", cascade="all, delete-orphan")
# tracking = relationship("OrderTracking", back_populates="order", uselist=False, cascade="all, delete-orphan")
# admin_notes = relationship("OrderNote", back_populates="order", cascade="all, delete-orphan")
# is_deleted = Column(Boolean, default=False, nullable=False)
# deleted_at = Column(DateTime(timezone=True), nullable=True)

# Add these to your existing Payment model:
# status_history = relationship("PaymentStatusHistory", back_populates="payment", cascade="all, delete-orphan")

# Add these to your existing Product model:
# reviews = relationship("Review", back_populates="product", cascade="all, delete-orphan")
# questions = relationship("ProductQuestion", back_populates="product", cascade="all, delete-orphan")
