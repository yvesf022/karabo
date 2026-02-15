from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import init_database, SessionLocal
from app.admin_auth import ensure_admin_exists

# Route modules
from app.routes import users, products, orders, payments, admin, health
from app.routes import admin_users, password_reset
from app.auth import router as auth_router
from app.admin_auth import router as admin_auth_router


# ======================================================
# APP
# ======================================================

app = FastAPI(
    title="Karabo API",
    version="1.0.0"
)


# ======================================================
# CORS (COOKIE-BASED AUTH SAFE)
# ======================================================

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


# ======================================================
# ROUTES
# ======================================================

# Health routes (NO /api prefix)
app.include_router(health.router)

# Auth routes (already internally prefixed)
app.include_router(auth_router)         # /api/auth/*
app.include_router(admin_auth_router)   # /api/admin/auth/*

# Core API routes
app.include_router(users.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(admin_users.router, prefix="/api")
app.include_router(password_reset.router, prefix="/api")


# ======================================================
# STARTUP (AUTO DB MIGRATION SAFE FOR RENDER FREE)
# ======================================================

@app.on_event("startup")
def startup():
    """
    Runs automatically on server start.

    Guarantees:
    - All tables exist
    - Admin account exists
    - Missing columns are auto-created (Render-safe)
    """

    # Create tables if missing
    init_database()

    db = SessionLocal()

    try:
        # Ensure admin exists
        ensure_admin_exists(db)

        # -------------------------------------------------
        # 🔥 AUTO FIX ORDERS TABLE (Checkout Fix)
        # -------------------------------------------------

        db.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS notes TEXT
        """))

        db.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS shipping_address JSON
        """))

        db.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE
        """))

        db.commit()

        print("✅ Database schema verified successfully")

    except Exception as e:
        print("❌ Startup migration failed:", e)

    finally:
        db.close()
