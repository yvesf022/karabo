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
    - Missing Payment columns are auto-added
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

        add_column_if_missing("products", "parent_asin", "VARCHAR")
        add_column_if_missing("products", "rating_number", "INTEGER DEFAULT 0")
        add_column_if_missing("products", "main_category", "VARCHAR")
        add_column_if_missing("products", "categories", "JSON")
        add_column_if_missing("products", "details", "JSON")
        add_column_if_missing("products", "features", "JSON")
        add_column_if_missing("products", "store", "VARCHAR")

        # ==================================================
        # 🔥 AUTO-SYNC PAYMENTS TABLE (SAFE MIGRATION)
        # ==================================================

        add_column_if_missing("payments", "admin_notes", "TEXT")
        add_column_if_missing("payments", "reviewed_by", "UUID")
        add_column_if_missing("payments", "reviewed_at", "TIMESTAMPTZ")

    # ==================================================
    # CREATE TABLES (AFTER ENUMS EXIST)
    # ==================================================

    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    print("✅ Database verified (enums, tables, indexes, FKs)")
    print("🔥 Products + Payments tables auto-synced successfully")
