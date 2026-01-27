from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 🔴 THIS LINE IS THE KEY
import app.models  # noqa: F401  (forces model registration)

from app.database import engine
from app.models import Base

from app.auth import router as auth_router
from app.routes import products, orders, users, admin

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
# CREATE TABLES (NOW WORKS)
# =========================
Base.metadata.create_all(bind=engine)

# =========================
# ROUTES
# =========================
app.include_router(auth_router)
app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/")
def root():
    return {"status": "ok"}
