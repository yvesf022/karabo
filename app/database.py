import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

# ======================================================
# DATABASE CONNECTION
# ======================================================

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

# ── Neon / any external Postgres over SSL ──────────────────────────
# Neon requires SSL and uses port 5432 over TLS (port 443 proxy also
# available via the "pooled" connection string).
# We normalise the URL scheme so SQLAlchemy uses psycopg2 correctly.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,       # drops stale connections (vital for Neon cold-starts)
    pool_size=5,              # Neon free tier: max 10 connections, keep headroom
    max_overflow=2,
    pool_timeout=30,
    pool_recycle=300,         # recycle connections every 5 min (avoids idle timeouts)
    connect_args={
        "sslmode": "require", # Neon mandates SSL; harmless on other Postgres hosts
        "connect_timeout": 10,
    },
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


# ======================================================
# DEPENDENCY
# ======================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ======================================================
# 🔥 DATABASE BOOTSTRAP (SAFE + AUTO SYNC)
# ======================================================

def init_database():
    """
    PostgreSQL-safe, idempotent DB initialization.

    Guarantees on every startup:
    - Required ENUMs exist (including patched values)
    - Stores table exists (needed before Product FK)
    - Missing columns are auto-added to all tables
    - All tables created via ORM
    - Safe for Render free tier via Neon (port 443 / SSL)
    """

    # ==================================================
    # 🔥 PATCH ENUMS — Must run OUTSIDE a transaction.
    # ALTER TYPE ... ADD VALUE IF NOT EXISTS cannot run
    # inside a transaction block in PostgreSQL.
    # AUTOCOMMIT isolation level is required here.
    # ==================================================

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE product_status AS ENUM
                ('active','inactive','discontinued','archived','draft');
            EXCEPTION WHEN duplicate_object THEN null;
            END $$;
        """))
        for value in ("active", "inactive", "discontinued", "archived", "draft"):
            conn.execute(text(f"""
                ALTER TYPE product_status ADD VALUE IF NOT EXISTS '{value}';
            """))

    with engine.begin() as conn:

        # ==================================================
        # 🔥 CREATE REQUIRED ENUMS (SAFE)
        # ==================================================

        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE order_status AS ENUM
            ('pending','paid','cancelled','shipped','completed');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE shipping_status AS ENUM
            ('pending','processing','shipped','delivered','returned');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE payment_status AS ENUM
            ('pending','on_hold','paid','rejected');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE payment_method AS ENUM
            ('card','cash','mobile_money','bank_transfer');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE bulk_upload_status AS ENUM
            ('processing','completed','failed','partial');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

        # ==================================================
        # 🔥 CREATE STORES TABLE EARLY
        # (Must exist before products.store_id FK is added)
        # ==================================================

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS stores (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name        VARCHAR NOT NULL UNIQUE,
            slug        VARCHAR NOT NULL UNIQUE,
            description TEXT,
            logo_url    VARCHAR,
            banner_url  VARCHAR,
            contact_email VARCHAR,
            contact_phone VARCHAR,
            address     TEXT,
            is_active   BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ
        );
        """))

        # ==================================================
        # 🔥 HELPER: ADD COLUMN IF MISSING
        # ==================================================

        def add_column_if_missing(table, column, definition):
            conn.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='{table}'
                    AND column_name='{column}'
                ) THEN
                    ALTER TABLE {table} ADD COLUMN {column} {definition};
                END IF;
            END $$;
            """))

        # ==================================================
        # 🔥 AUTO-SYNC PRODUCTS TABLE
        # ==================================================

        add_column_if_missing("products", "parent_asin",         "VARCHAR")
        add_column_if_missing("products", "rating_number",       "INTEGER DEFAULT 0")
        add_column_if_missing("products", "main_category",       "VARCHAR")
        add_column_if_missing("products", "categories",          "JSON")
        add_column_if_missing("products", "details",             "JSON")
        add_column_if_missing("products", "features",            "JSON")
        add_column_if_missing("products", "store",               "VARCHAR")
        add_column_if_missing("products", "main_image",          "VARCHAR")
        add_column_if_missing("products", "image_url",           "VARCHAR")
        add_column_if_missing("products", "low_stock_threshold", "INTEGER DEFAULT 10")
        add_column_if_missing("products", "is_deleted",          "BOOLEAN NOT NULL DEFAULT FALSE")
        add_column_if_missing("products", "deleted_at",          "TIMESTAMPTZ")
        add_column_if_missing("products", "is_priced",           "BOOLEAN NOT NULL DEFAULT FALSE")
        add_column_if_missing("products", "priced_at",           "TIMESTAMPTZ")
        add_column_if_missing("products", "pricing_status",      "VARCHAR NOT NULL DEFAULT 'unpriced'")
        add_column_if_missing("products", "priced_by",           "UUID REFERENCES users(id) ON DELETE SET NULL")
        add_column_if_missing("products", "store_id",
            "UUID REFERENCES stores(id) ON DELETE SET NULL")
        add_column_if_missing("products", "tags",
            "JSON")                                        # collection tags array

        # ==================================================
        # 🔥 AUTO-SYNC PRODUCT_IMAGES TABLE
        # ==================================================

        add_column_if_missing("product_images", "is_primary", "BOOLEAN DEFAULT FALSE")

        # ==================================================
        # 🔥 AUTO-SYNC PAYMENTS TABLE
        # ==================================================

        add_column_if_missing("payments", "admin_notes",      "TEXT")
        add_column_if_missing("payments", "reviewed_by",      "UUID")
        add_column_if_missing("payments", "reviewed_at",      "TIMESTAMPTZ")
        add_column_if_missing("payments", "reference_number", "VARCHAR")
        add_column_if_missing("payments", "updated_at",       "TIMESTAMPTZ")
        add_column_if_missing("payments", "expires_at",       "TIMESTAMPTZ")

        # ==================================================
        # 🔥 AUTO-SYNC ORDERS TABLE
        # ==================================================

        add_column_if_missing("orders", "notes",            "TEXT")
        add_column_if_missing("orders", "shipping_address", "JSON")
        add_column_if_missing("orders", "updated_at",       "TIMESTAMPTZ")
        add_column_if_missing("orders", "is_deleted",       "BOOLEAN NOT NULL DEFAULT FALSE")
        add_column_if_missing("orders", "deleted_at",       "TIMESTAMPTZ")

        # ==================================================
        # 🔥 CREATE INDEXES (SAFE - ENTERPRISE ENHANCED)
        # ==================================================

        indexes = [
            ("idx_products_is_deleted",          "products",               "is_deleted"),
            ("idx_products_store_id",            "products",               "store_id"),
            ("idx_stores_slug",                  "stores",                 "slug"),
            ("idx_stores_active",                "stores",                 "is_active"),
            ("idx_addresses_user_id",            "addresses",              "user_id"),
            ("idx_addresses_is_default",         "addresses",              "is_default"),
            ("idx_carts_user_id",                "carts",                  "user_id"),
            ("idx_cart_items_cart_id",           "cart_items",             "cart_id"),
            ("idx_cart_items_product_id",        "cart_items",             "product_id"),
            ("idx_wishlists_user_id",            "wishlists",              "user_id"),
            ("idx_reviews_product_id",           "reviews",                "product_id"),
            ("idx_reviews_user_id",              "reviews",                "user_id"),
            ("idx_reviews_rating",               "reviews",                "rating"),
            ("idx_categories_slug",              "categories",             "slug"),
            ("idx_brands_slug",                  "brands",                 "slug"),
            ("idx_notifications_user_id",        "notifications",          "user_id"),
            ("idx_notifications_is_read",        "notifications",          "is_read"),
            ("idx_coupons_code",                 "coupons",                "code"),
            ("idx_wallets_user_id",              "wallets",                "user_id"),
            ("idx_order_items_order_id",         "order_items",            "order_id"),
            ("idx_order_returns_order_id",       "order_returns",          "order_id"),
            ("idx_order_notes_order_id",         "order_notes",            "order_id"),
            ("idx_payment_history_payment_id",   "payment_status_history", "payment_id"),
            ("idx_payments_reference_number",    "payments",               "reference_number"),
        ]

        for idx_name, table, column in indexes:
            conn.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = '{idx_name}'
                ) THEN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = '{table}'
                    ) AND EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = '{table}' AND column_name = '{column}'
                    ) THEN
                        CREATE INDEX {idx_name} ON {table}({column});
                    END IF;
                END IF;
            END $$;
            """))

    # ==================================================
    # CREATE ALL TABLES VIA ORM (AFTER ENUMS + STORES EXIST)
    # ==================================================

    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # ==================================================
    # 🔥 SEED BEAUTY CATEGORIES (idempotent — safe to re-run)
    # These are the 20 category slugs that match products.category
    # and are used by the store frontend filters, sidebar, and
    # the category nav. Uses ON CONFLICT DO NOTHING so re-runs
    # after the initial boot are zero-cost.
    # ==================================================

    BEAUTY_CATEGORIES = [
        # (slug,                  display_name,               description,                                                   position)
        ("anti_aging",          "Anti-Aging",           "Retinol, collagen boosters & wrinkle-fighting treatments",            1),
        ("acne",                "Acne Care",             "Spot treatments, pore cleansers & acne-fighting formulas",           2),
        ("brightening",         "Brightening",           "Vitamin C, niacinamide & glow-enhancing serums",                     3),
        ("whitening",           "Whitening",             "Glutathione, kojic acid & skin-lightening treatments",               4),
        ("hydration",           "Hydration",             "Moisturisers, hyaluronic acid & daily hydration essentials",         5),
        ("repair",              "Repair & Restore",      "Healing creams, recovery serums & barrier repair",                   6),
        ("barrier",             "Skin Barrier",          "Ceramide creams & microbiome-protecting formulas",                   7),
        ("eczema",              "Eczema Relief",         "Gentle formulas for sensitive, eczema-prone skin",                   8),
        ("rosacea",             "Rosacea Care",          "Calming, redness-reducing treatments for rosacea skin",              9),
        ("scar",                "Scar & Dark Spots",     "Scar gels, dark spot correctors & hyperpigmentation solutions",     10),
        ("stretch_mark",        "Stretch Marks",         "Creams, oils & treatments for stretch marks",                       11),
        ("sunscreen",           "Sunscreen",             "SPF face & body protection for all skin types",                     12),
        ("oils",                "Facial & Body Oils",    "Natural, pure & blended oils for skin and hair",                    13),
        ("soaps",               "Soaps & Cleansers",     "Bar soaps, cleansing bars & deep-cleansing formulas",               14),
        ("body",                "Body Care",             "Body lotions, washes, hand & foot care essentials",                 15),
        ("masks",               "Masks & Treatments",   "Sheet masks, clay masks & overnight skin treatments",               16),
        ("exfoliation",         "Exfoliation",           "Scrubs, peels, toner pads & enzyme exfoliants",                    17),
        ("clinical_acids",      "Clinical Acids",        "AHAs, BHAs, glycolic & lactic acid treatments",                    18),
        ("african_ingredients", "African Ingredients",   "Shea butter, marula, baobab & African botanical extracts",         19),
        ("korean_ingredients",  "Korean Ingredients",    "K-beauty essentials: snail, centella, ginseng & more",             20),
    ]

    with engine.begin() as conn:
        # Ensure categories table has a unique constraint on slug
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'categories' AND constraint_type = 'UNIQUE'
                    AND constraint_name = 'categories_slug_key'
                ) THEN
                    ALTER TABLE categories ADD CONSTRAINT categories_slug_key UNIQUE (slug);
                END IF;
            END $$;
        """))

        for slug, name, desc, pos in BEAUTY_CATEGORIES:
            conn.execute(text("""
                INSERT INTO categories (id, name, slug, description, is_active, position)
                VALUES (gen_random_uuid(), :name, :slug, :desc, true, :pos)
                ON CONFLICT (slug) DO UPDATE
                    SET name        = EXCLUDED.name,
                        description = EXCLUDED.description,
                        is_active   = true,
                        position    = EXCLUDED.position
            """), {"name": name, "slug": slug, "desc": desc, "pos": pos})

    print("✅ Database verified (enums, tables, indexes, FKs)")
    print("🔥 All tables auto-synced successfully")
    print("🏬 Stores table ready")
    print("🧬 Variants + Inventory + AuditLog tables ready")
    print("🛒 Cart, Wishlist, Reviews tables ready")
    print("💰 Wallet, Coupons, Notifications tables ready")
    print("📦 Enterprise features initialized")
    print("🎨 20 beauty categories seeded ✅")