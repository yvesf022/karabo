from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

# Core auth
from app.auth import router as auth_router

# Other routes
from app.routes.admin import router as admin_router
from app.routes.orders import router as orders_router
from app.routes.products import router as products_router
from app.routes.users import router as users_router

app = FastAPI(
    title="Karabo E-Commerce API",
    version="1.0.0",
)

# --------------------------------------------------
# LOGGING
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)

# --------------------------------------------------
# CORS (VERCEL + LOCAL)
# --------------------------------------------------

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

# --------------------------------------------------
# ROUTERS
# --------------------------------------------------

app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(products_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(admin_router, prefix="/api/admin")

# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/")
def root():
    return {"status": "ok"}
