import os
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.models import Base, User
from app.security import hash_password
from app.routes import auth, admin, products, orders, users

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# APP INIT
# =========================
app = FastAPI(
    title="Karabo E-Commerce API",
    version="1.0.0",
)

# =========================
# GLOBAL EXCEPTION HANDLER
# =========================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)},
    )

# =========================
# CORS (FIXED — PROD SAFE)
# =========================
ALLOWED_ORIGINS = [
    "https://kkkkkk-kappa.vercel.app",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# ROUTES
# =========================
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")

# =========================
# ADMIN SEED
# =========================
def seed_admin():
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")

    if not email or not password:
        logger.info("ADMIN_EMAIL or ADMIN_PASSWORD not set — skipping admin seed")
        return

    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.email == email).first()

        if not admin_user:
            admin_user = User(
                email=email,
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
            )
            db.add(admin_user)
            db.commit()
            logger.info("✅ Admin user created")
        else:
            updated = False

            if admin_user.role != "admin":
                admin_user.role = "admin"
                updated = True

            if not admin_user.password_hash:
                admin_user.password_hash = hash_password(password)
                updated = True

            if updated:
                db.commit()
                logger.info("ℹ️ Admin user repaired")
            else:
                logger.info("ℹ️ Admin user already valid")
    finally:
        db.close()

# =========================
# DB MIGRATIONS (SAFE)
# =========================
def migrate_orders_and_payments():
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS payment_status TEXT;
        """))
        db.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS shipping_status TEXT;
        """))
        db.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS tracking_number TEXT;
        """))

        db.execute(text("""
            ALTER TABLE payments
            ADD COLUMN IF NOT EXISTS status TEXT;
        """))
        db.execute(text("""
            ALTER TABLE payments
            ADD COLUMN IF NOT EXISTS proof_url TEXT;
        """))

        db.commit()
        logger.info("✅ orders & payments columns verified")
    except Exception as e:
        logger.error(f"❌ orders/payments migration failed: {e}")
    finally:
        db.close()

def migrate_address_link():
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS address_id UUID;
        """))

        db.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE constraint_name = 'orders_address_id_fkey'
                ) THEN
                    ALTER TABLE orders DROP CONSTRAINT orders_address_id_fkey;
                END IF;
            END$$;
        """))

        db.execute(text("""
            ALTER TABLE orders
            ADD CONSTRAINT orders_address_id_fkey
            FOREIGN KEY (address_id)
            REFERENCES addresses(id)
            ON DELETE SET NULL;
        """))

        db.commit()
        logger.info("✅ orders.address_id UUID FK verified")
    except Exception as e:
        logger.error(f"❌ address_id migration failed: {e}")
    finally:
        db.close()

def migrate_products_inventory():
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS stock INTEGER NOT NULL DEFAULT 0;
        """))
        db.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS in_stock BOOLEAN NOT NULL DEFAULT FALSE;
        """))

        db.execute(text("""
            UPDATE products
            SET in_stock = (stock > 0)
            WHERE in_stock = FALSE;
        """))

        db.commit()
        logger.info("✅ products stock & in_stock columns verified")
    except Exception as e:
        logger.error(f"❌ products inventory migration failed: {e}")
    finally:
        db.close()

# =========================
# STARTUP
# =========================
@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)
    migrate_orders_and_payments()
    migrate_address_link()
    migrate_products_inventory()
    seed_admin()

# =========================
# ROOT
# =========================
@app.get("/")
def root():
    return {"status": "ok", "message": "Karabo backend is running"}
