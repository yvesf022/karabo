from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router
from app.routes import products, orders, users, admin

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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# ROUTES
# =========================================================

# ❗ auth_router already has /api/auth prefix internally
app.include_router(auth_router, tags=["auth"])

app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/")
def health_check():
    return {"status": "ok"}
