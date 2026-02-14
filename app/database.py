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
    - Missing Product columns are auto-added
    - Tables exist
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
        # 🔥 AUTO-SYNC PRODUCTS TABLE (SAFE MIGRATION)
        # ==================================================

        # parent_asin
        conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='products'
                AND column_name='parent_asin'
            ) THEN
                ALTER TABLE products ADD COLUMN parent_asin VARCHAR;
            END IF;
        END $$;
        """))

        # rating_number
        conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='products'
                AND column_name='rating_number'
            ) THEN
                ALTER TABLE products ADD COLUMN rating_number INTEGER DEFAULT 0;
            END IF;
        END $$;
        """))

        # main_category
        conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='products'
                AND column_name='main_category'
            ) THEN
                ALTER TABLE products ADD COLUMN main_category VARCHAR;
            END IF;
        END $$;
        """))

        # categories
        conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='products'
                AND column_name='categories'
            ) THEN
                ALTER TABLE products ADD COLUMN categories JSON;
            END IF;
        END $$;
        """))

        # details
        conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='products'
                AND column_name='details'
            ) THEN
                ALTER TABLE products ADD COLUMN details JSON;
            END IF;
        END $$;
        """))

        # features
        conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='products'
                AND column_name='features'
            ) THEN
                ALTER TABLE products ADD COLUMN features JSON;
            END IF;
        END $$;
        """))

        # store
        conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='products'
                AND column_name='store'
            ) THEN
                ALTER TABLE products ADD COLUMN store VARCHAR;
            END IF;
        END $$;
        """))

    # ==================================================
    # CREATE TABLES (AFTER ENUMS EXIST)
    # ==================================================

    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    print("✅ Database verified (enums, tables, indexes, FKs)")
    print("🔥 Products table auto-synced successfully")
