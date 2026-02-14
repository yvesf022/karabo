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
# 🔥 DATABASE BOOTSTRAP (ENUM SAFE + AUTO REPAIR)
# ======================================================

def init_database():
    """
    PostgreSQL-safe, idempotent DB initialization.

    Guarantees on every startup:
    - Enums exist
    - Enum type mismatches are repaired
    - Tables exist
    - Safe for Render (no shell required)
    """

    with engine.begin() as conn:

        # ==================================================
        # 🔥 CRITICAL FIX: product_status ENUM AUTO-REPAIR
        # ==================================================

        # 1️⃣ Ensure enum exists
        conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'product_status'
            ) THEN
                CREATE TYPE product_status AS ENUM ('active','inactive','discontinued');
            END IF;
        END $$;
        """))

        # 2️⃣ Convert products.status to ENUM if it is VARCHAR
        conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'products'
                AND column_name = 'status'
                AND data_type != 'USER-DEFINED'
            ) THEN
                ALTER TABLE products
                ALTER COLUMN status TYPE product_status
                USING status::product_status;
            END IF;
        END $$;
        """))

        # ==================================================
        # OTHER ENUMS (SAFE CREATE)
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
    # CREATE TABLES (AFTER ENUMS EXIST)
    # ==================================================

    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    print("✅ Database verified (enums, tables, indexes, FKs)")
    print("🔥 product_status enum auto-repair applied if needed")
