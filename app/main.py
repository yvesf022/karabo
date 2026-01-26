import os
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import SessionLocal, engine
from app.models import Base, User
from app.security import hash_password
from app.routes import auth, admin, products, orders

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
# DATABASE
# =========================
Base.metadata.create_all(bind=engine)

# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# ROUTES
# =========================
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")

# =========================
# ADMIN SEED (FIXED)
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
                password_hash=hash_password(password),  # ✅ FIXED FIELD NAME
                role="admin",
                is_active=True,
            )
            db.add(admin_user)
            db.commit()
            logger.info("✅ Admin user created from environment variables")

        else:
            # Optional: ensure existing admin is really admin
            if admin_user.role != "admin":
                admin_user.role = "admin"
                db.commit()
                logger.info("ℹ️ Existing user promoted to admin")

            logger.info("ℹ️ Admin user already exists — no action taken")

    finally:
        db.close()


@app.on_event("startup")
def startup_event():
    seed_admin()


# =========================
# ROOT & HEALTH
# =========================
@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Karabo backend is running",
    }


@app.get("/api")
def api_index():
    return {
        "auth": {
            "login": "POST /api/auth/login",
            "register": "POST /api/auth/register",
            "me": "GET /api/auth/me",
        },
        "admin": {
            "me": "GET /api/admin/me",
            "payment_settings": "GET/POST /api/admin/payment-settings",
        },
        "products": "GET /api/products",
        "orders": "GET /api/orders",
    }
