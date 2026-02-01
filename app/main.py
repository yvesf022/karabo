from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_database

# Existing routes
from app.routes import users, products, orders, payments, admin
from app.auth import router as auth_router
from app.admin_auth import router as admin_auth_router

# ✅ NEW routes we added
from app.routes import admin_users, password_reset

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
# STATIC FILES
# =========================

# Product images, order uploads, etc.
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# User avatars (static/avatars)
app.mount("/static", StaticFiles(directory="static"), name="static")

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

# ✅ Admin user management
app.include_router(admin_users.router, prefix="/api")

# ✅ Password reset
app.include_router(password_reset.router, prefix="/api")

# =========================
# STARTUP
# =========================

@app.on_event("startup")
def startup():
    """
    Guarantees:
    - DB enums exist
    - DB tables exist
    - DB indexes & FKs exist
    Safe to run on every startup.
    """
    init_database()
