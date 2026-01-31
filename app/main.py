from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.database import engine, Base
from app.routes import users, products, orders, payments, admin
from app.auth import router as auth_router
from app.admin_auth import router as admin_auth_router

app = FastAPI(title="Karabo API")

# =========================
# CORS (COOKIE SAFE)
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kkkkkk-kappa.vercel.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# STATIC FILES (UPLOADS)
# =========================
# 🔥 REQUIRED FOR PRODUCT IMAGES
app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads",
)

# =========================
# ROUTES
# =========================

# Auth
app.include_router(auth_router)          # /api/auth/*
app.include_router(admin_auth_router)    # /api/admin/auth/*

# Core API
app.include_router(users.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

# =========================
# 🔥 AUTO-FIX DATABASE (SAFE, IDEMPOTENT)
# =========================

@app.on_event("startup")
def on_startup():
    """
    This guarantees the Product table always has
    all required columns.

    - Safe to run on every startup
    - Does NOT drop data
    - Adds missing columns only
    """

    # Create tables that do not exist
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        # -------------------------
        # PRODUCT CORE FIELDS
        # -------------------------
        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS short_description TEXT;
        """))

        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS description TEXT;
        """))

        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS main_image TEXT;
        """))

        # -------------------------
        # PRICING
        # -------------------------
        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS compare_price NUMERIC;
        """))

        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS rating NUMERIC;
        """))

        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS sales INTEGER DEFAULT 0;
        """))

        # -------------------------
        # INVENTORY / STATUS
        # -------------------------
        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS in_stock BOOLEAN DEFAULT TRUE;
        """))

        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';
        """))

        # -------------------------
        # METADATA
        # -------------------------
        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS sku TEXT;
        """))

        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS brand TEXT;
        """))

        # -------------------------
        # ADVANCED (JSON SUPPORT)
        # -------------------------
        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS images JSONB;
        """))

        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS specs JSONB;
        """))

        # -------------------------
        # TIMESTAMPS (SAFE DEFAULTS)
        # -------------------------
        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
        """))

        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
        """))

    print("✅ Product table verified and auto-upgraded")
