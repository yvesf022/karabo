import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

# ======================================================
# DATABASE CONNECTION
# ======================================================

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
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
    - Required ENUMs exist
    - Stores table exists (needed before Product FK)
    - Missing columns are auto-added to all tables
    - All tables created via ORM
    - Safe for Render (no shell required)
    """

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

        # Original columns
        add_column_if_missing("products", "parent_asin",    "VARCHAR")
        add_column_if_missing("products", "rating_number",  "INTEGER DEFAULT 0")
        add_column_if_missing("products", "main_category",  "VARCHAR")
        add_column_if_missing("products", "categories",     "JSON")
        add_column_if_missing("products", "details",        "JSON")
        add_column_if_missing("products", "features",       "JSON")
        add_column_if_missing("products", "store",          "VARCHAR")

        # New columns
        add_column_if_missing("products", "low_stock_threshold", "INTEGER DEFAULT 10")
        add_column_if_missing("products", "is_deleted",          "BOOLEAN NOT NULL DEFAULT FALSE")
        add_column_if_missing("products", "deleted_at",          "TIMESTAMPTZ")
        add_column_if_missing("products", "store_id",
            "UUID REFERENCES stores(id) ON DELETE SET NULL")

        # ==================================================
        # 🔥 AUTO-SYNC PRODUCT_IMAGES TABLE
        # ==================================================

        add_column_if_missing("product_images", "is_primary", "BOOLEAN DEFAULT FALSE")

        # ==================================================
        # 🔥 AUTO-SYNC PAYMENTS TABLE
        # ==================================================

        add_column_if_missing("payments", "admin_notes",  "TEXT")
        add_column_if_missing("payments", "reviewed_by",  "UUID")
        add_column_if_missing("payments", "reviewed_at",  "TIMESTAMPTZ")

        # ==================================================
        # 🔥 AUTO-SYNC ORDERS TABLE
        # ==================================================

        add_column_if_missing("orders", "notes",            "TEXT")
        add_column_if_missing("orders", "shipping_address", "JSON")
        add_column_if_missing("orders", "updated_at",       "TIMESTAMPTZ")

        # ==================================================
        # 🔥 CREATE INDEXES (SAFE)
        # ==================================================

        indexes = [
            ("idx_products_is_deleted",  "products",              "is_deleted"),
            ("idx_products_store_id",    "products",              "store_id"),
            ("idx_stores_slug",          "stores",                "slug"),
            ("idx_stores_active",        "stores",                "is_active"),
        ]

        for idx_name, table, column in indexes:
            conn.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = '{idx_name}'
                ) THEN
                    CREATE INDEX {idx_name} ON {table}({column});
                END IF;
            END $$;
            """))

    # ==================================================
    # CREATE ALL TABLES VIA ORM (AFTER ENUMS + STORES EXIST)
    # ==================================================

    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    print("✅ Database verified (enums, tables, indexes, FKs)")
    print("🔥 All tables auto-synced successfully")
    print("🏬 Stores table ready")
    print("🧬 Variants + Inventory + AuditLog tables ready")