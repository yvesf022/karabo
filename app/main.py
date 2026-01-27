from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.auth import router as auth_router
from app.routes.products import router as products_router
from app.routes.orders import router as orders_router
from app.routes.admin import router as admin_router
from app.routes.users import router as users_router

# =========================
# APP INIT
# =========================

app = FastAPI(
    title="Karabo API",
    version="1.0.0",
)

# =========================
# DATABASE
# =========================

Base.metadata.create_all(bind=engine)

# =========================
# CORS (CRITICAL)
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kkkkkk-kappa.vercel.app",  # production frontend
        "http://localhost:3000",             # local dev frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# ROUTERS
# =========================

app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(users_router, prefix="/api/users", tags=["Users"])
app.include_router(products_router, prefix="/api/products", tags=["Products"])
app.include_router(orders_router, prefix="/api/orders", tags=["Orders"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])

# =========================
# ROOT
# =========================

@app.get("/")
def root():
    return {"status": "OK", "service": "Karabo Backend"}
