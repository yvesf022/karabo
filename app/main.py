from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router
from app.routes.products import router as products_router
from app.routes.orders import router as orders_router
from app.routes.users import router as users_router
from app.routes.admin import router as admin_router

app = FastAPI(title="Karabo API")

# =========================
# CORS (REQUIRED FOR VERCEL)
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# ROUTES
# =========================
app.include_router(auth_router)
app.include_router(products_router)
app.include_router(orders_router)
app.include_router(users_router)
app.include_router(admin_router)


@app.get("/")
def health():
    return {"status": "ok"}
