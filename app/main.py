from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import Base, engine
from app.routes import auth, admin, products, orders
import os
import logging

# --------------------------------------------------
# BASIC LOGGING
# --------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("karabo-backend")

# --------------------------------------------------
# DATABASE INIT (AUTO CREATE TABLES)
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
# CORS (OPEN FOR NOW)
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# UPLOAD DIRECTORIES (ALIGNED WITH ROUTES)
# --------------------------------------------------
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

PRODUCT_DIR = os.path.join(UPLOAD_DIR, "products")
PAYMENT_DIR = os.path.join(UPLOAD_DIR, "payments")

os.makedirs(PRODUCT_DIR, exist_ok=True)
os.makedirs(PAYMENT_DIR, exist_ok=True)

logger.info(f"Upload directories ready at '{UPLOAD_DIR}'")

# --------------------------------------------------
# STATIC FILES (SERVE UPLOADS)
# --------------------------------------------------
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------
@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "Karabo's Boutique API",
    }

# --------------------------------------------------
# API INDEX (ACCURATE, NO LEGACY INFO)
# --------------------------------------------------
@app.get("/api")
def api_index():
    return {
        "message": "Karabo's Boutique API is running",
        "auth": {
            "register": "POST /api/auth/register",
            "login": "POST /api/auth/login",
        },
        "products": "GET /api/products",
        "orders": "POST /api/orders",
        "admin": "Protected routes under /api/admin/*",
        "note": "Most endpoints require Authorization: Bearer <token>",
    }

# --------------------------------------------------
# ROUTES (SINGLE /api PREFIX ONLY)
# --------------------------------------------------
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")

logger.info("Routes registered successfully")
