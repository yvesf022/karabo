import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================
# 🔥 DATABASE BOOTSTRAP
# =========================

def init_database():
    """
    PostgreSQL-safe, idempotent DB initialization.
    - Enums
    - Tables
    - Indexes
    - Foreign keys
    """

    with engine.begin() as conn:

        # -------------------------
        # ENUMS (SAFE CREATE)
        # -------------------------
        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE product_status AS ENUM ('active','inactive','discontinued');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE order_status AS ENUM ('pending','paid','cancelled','shipped','completed');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE shipping_status AS ENUM ('pending','processing','shipped','delivered','returned');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE payment_status AS ENUM ('pending','on_hold','paid','rejected');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

        conn.execute(text("""
        DO $$ BEGIN
            CREATE TYPE payment_method AS ENUM ('card','cash','mobile_money','bank_transfer');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """))

    # -------------------------
    # TABLES & INDEXES
    # -------------------------
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    print("✅ Database verified (enums, tables, indexes, FKs)")
