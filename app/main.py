from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import products, orders, users, admin
from app.auth import router as auth_router

app = FastAPI()

# =========================================================
# CORS — MUST BE FIRST
# =========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://kkkkkk-kappa.vercel.app",
    ],
    allow_credentials=True,  # 🔐 REQUIRED FOR COOKIES
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# ROUTES
# =========================================================
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/")
def health_check():
    return {"status": "ok"}
