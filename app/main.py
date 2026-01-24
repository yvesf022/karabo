from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import Base, engine
from app.routes import auth, admin, products, orders
import os

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Karabo’s Boutique API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
os.makedirs(f"{UPLOAD_DIR}/products", exist_ok=True)
os.makedirs(f"{UPLOAD_DIR}/orders", exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

@app.get("/")
def health():
    return {"status": "ok"}

app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(products.router, prefix="/api/products")
app.include_router(orders.router, prefix="/api/orders")
