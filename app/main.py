# -*- coding: utf-8 -*-

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import Base, engine
from app.routes import auth, admin, products, orders
import os
import logging

# --------------------------------------------------
# BASIC LOGGING (helps a LOT on Render free tier)
# --------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("karabo-backend")

# --------------------------------------------------
# DATABASE INIT (auto-create tables on deploy)
# --------------------------------------------------
Base.metadata.create_all(bind=engine)
logger.info("Database tables ensured")

# --------------------------------------------------
# FASTAPI APP
# --------------------------------------------------
app = FastAPI(
    title="Karabo's Boutique API",
    description="Backend API for Karabo's Boutique (Render + Netlify)",
    version="1.0.0",
)

# --------------------------------------------------
# CORS (open for now, tighten later)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# UPLOAD DIRECTORIES
# --------------------------------------------------
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

PRODUCT_DIR = os.path.join(UPLOAD_DIR, "products")
ORDER_DIR = os.path.join(UPLOAD_DIR, "orders")

os.makedirs(PRODUCT_DIR, exist_ok=True)
os.makedirs(ORDER_DIR, exist_ok=True)

logger.info(f"Upload directories ready at '{UPLOAD_DIR}'")

# --------------------------------------------------
# STATIC FILES
# --------------------------------------------------
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --------------------------------------------------
# HEALTH CHECK (Render / browser friendly)
# --------------------------------------------------
@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "Karabo's Boutique API",
    }

# --------------------------------------------------
# API INDEX (IMPORTANT FOR BROWSER TESTING)
# --------------------------------------------------
@app.get("/api")
def api_index():
    return {
        "message": "Karabo's Boutique API is running",
        "admin_login": "POST /api/admin/login",
        "customer_login": "POST /api/auth/login",
        "products": "GET /api/products",
        "note": "POST endpoints require JSON body",
    }

# --------------------------------------------------
# ADMIN LOGIN INFO (PREVENTS METHOD CONFUSION)
# --------------------------------------------------
@app.get("/api/admin/login-info")
def admin_login_info():
    return {
        "how_to_login": "Send a POST request to /api/admin/login",
        "headers": {
            "Content-Type": "application/json"
        },
        "body_example": {
            "email": "admin@karabos.com",
            "password": "Admin@123"
        },
        "note": "Opening /api/admin/login in a browser will NOT work (POST only)"
    }

# --------------------------------------------------
# ROUTES
# --------------------------------------------------
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(products.router, prefix="/api/products")
app.include_router(orders.router, prefix="/api/orders")

logger.info("Routes registered successfully")
