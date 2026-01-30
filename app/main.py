from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# 🔴 FORCE MODEL REGISTRATION
import app.models  # noqa: F401

from app.database import engine, SessionLocal
from app.models import Base, User
from app.security import hash_password

from app.auth import router as auth_router
from app.admin_auth import router as admin_auth_router
from app.routes import products, orders, users, admin, payments

# =========================
# APP
# =========================
app = FastAPI(title="Karabo API")

# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://kkkkkk-kappa.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# CREATE TABLES
# =========================
Base.metadata.create_all(bind=engine)

# =========================
# ADMIN BOOTSTRAP (ENV BASED)
# =========================
def ensure_admin_user():
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")

    # 🔒 If env vars not set, admin login is disabled (SAFE)
    if not admin_email or not admin_password:
        print("⚠️ ADMIN_EMAIL / ADMIN_PASSWORD not set")
        return

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == admin_email).first()
        if not admin:
            admin = User(
                email=admin_email,
                password_hash=hash_password(admin_password),
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            print("✅ Admin account created from environment variables")
        else:
            print("ℹ️ Admin account already exists")
    finally:
        db.close()

ensure_admin_user()

# =========================
# ROUTES
# =========================
app.include_router(auth_router)
app.include_router(admin_auth_router)

app.include_router(products.router, prefix="/api", tags=["products"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

# =========================
# HEALTH CHECK
# =========================
@app.get("/")
def root():
    return {"status": "ok"}
