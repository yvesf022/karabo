from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import os

from app.database import init_database, SessionLocal
from app.admin_auth import ensure_admin_exists

# Routes
from app.routes import users, products, orders, payments, admin
from app.routes import admin_users, password_reset
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
# FILE SYSTEM SETUP
# =========================

# Ensure upload directories exist (CRITICAL)
UPLOAD_DIRS = [
    "static",
    "static/avatars",
    "uploads",
    "uploads/products",
    "uploads/payments",
]

for path in UPLOAD_DIRS:
    os.makedirs(path, exist_ok=True)

# =========================
# STATIC FILES
# =========================

# User avatars
app.mount("/static", StaticFiles(directory="static"), name="static")

# Product images, payment proofs, etc.
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

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

# Admin user management
app.include_router(admin_users.router, prefix="/api")

# Password reset
app.include_router(password_reset.router, prefix="/api")

# =========================
# STARTUP
# =========================

@app.on_event("startup")
def startup():
    """
    Guarantees on every startup:
    - Database tables exist
    - Admin user exists (from ENV)
    - Upload directories exist
    """
    # DB setup
    init_database()

    # Admin bootstrap
    db = SessionLocal()
    try:
        ensure_admin_exists(db)
    finally:
        db.close()
