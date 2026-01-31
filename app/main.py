from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
# 🔥 AUTO-FIX DATABASE (Render Free)
# =========================

@app.on_event("startup")
def on_startup():
    # Creates missing tables & columns
    Base.metadata.create_all(bind=engine)
