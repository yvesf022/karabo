from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import init_database, SessionLocal
from app.admin_auth import ensure_admin_exists

# Route modules - Existing
from app.routes import users, products, orders, payments, admin, health
from app.routes import admin_users, password_reset
from app.auth import router as auth_router
from app.admin_auth import router as admin_auth_router

# Route modules - Enterprise Features
from app.routes import (
    addresses,
    cart,
    wishlist,
    reviews,
    product_qa,
    search,
    categories_brands,
    notifications,
    recently_viewed,
    coupons,
    order_enhancements,
    payment_enhancements,
    wallet,
    admin_orders_advanced,
    admin_payments_advanced,
    admin_users_advanced,
    homepage_sections,          # ← Smart homepage sections
    random_products,            # ← Random products endpoint
)
from app.routes import categories_router as categories_router   # ← Dynamic category images


app = FastAPI(title="Karabo API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kkkkkk-kappa.vercel.app",
        "https://karabostore.com",
        "https://www.karabostore.com",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health & Auth ──────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(auth_router)
app.include_router(admin_auth_router)

# ── Core API ───────────────────────────────────────────────────────
app.include_router(users.router,           prefix="/api")
app.include_router(products.router,        prefix="/api")
app.include_router(orders.router,          prefix="/api")
app.include_router(payments.router,        prefix="/api")
app.include_router(admin.router,           prefix="/api")
app.include_router(admin_users.router,     prefix="/api")
app.include_router(password_reset.router,  prefix="/api")

# ── Enterprise — User ──────────────────────────────────────────────
app.include_router(addresses.router,            prefix="/api")
app.include_router(cart.router,                 prefix="/api")
app.include_router(wishlist.router,             prefix="/api")
app.include_router(reviews.router,              prefix="/api")
app.include_router(product_qa.router,           prefix="/api")
app.include_router(search.router,               prefix="/api")
app.include_router(categories_brands.router,    prefix="/api")
app.include_router(notifications.router,        prefix="/api")
app.include_router(recently_viewed.router,      prefix="/api")
app.include_router(coupons.router,              prefix="/api")
app.include_router(order_enhancements.router,   prefix="/api")
app.include_router(payment_enhancements.router, prefix="/api")
app.include_router(wallet.router,               prefix="/api")

# ── Enterprise — Admin ─────────────────────────────────────────────
app.include_router(admin_orders_advanced.router,   prefix="/api")
app.include_router(admin_payments_advanced.router,  prefix="/api")
app.include_router(admin_users_advanced.router,     prefix="/api")

# ── Homepage Sections (smart product categoriser) ──────────────────
app.include_router(homepage_sections.router, prefix="/api")
# Endpoint: GET /api/homepage/sections

# ── Random Products (hero grid, discovery carousels) ───────────────
app.include_router(random_products.router, prefix="/api")

# ── Dynamic Category Images (beauty subcats + phone brands) ────────
app.include_router(categories_router.router, prefix="/api")
# Endpoint: GET /api/categories/departments
# Endpoints:
#   GET /api/products/random?count=20&with_images=true&seed=<int>&exclude=id1,id2
#   GET /api/products/random/categories?per_category=6&max_cats=12


@app.on_event("startup")
def startup():
    init_database()
    db = SessionLocal()
    try:
        ensure_admin_exists(db)
        db.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS notes TEXT"))
        db.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_address JSON"))
        db.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE"))
        db.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE"))
        db.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE"))
        db.execute(text("UPDATE products SET is_deleted = FALSE WHERE is_deleted IS NULL"))
        db.execute(text("UPDATE orders   SET is_deleted = FALSE WHERE is_deleted IS NULL"))

        # ✅ Backfill main_image for all products where it is NULL
        # (products imported before this column was populated)
        db.execute(text("""
            UPDATE products
            SET main_image = (
                SELECT image_url
                FROM product_images
                WHERE product_images.product_id = products.id
                ORDER BY is_primary DESC NULLS LAST, position ASC
                LIMIT 1
            )
            WHERE (main_image IS NULL OR main_image = '')
              AND EXISTS (
                SELECT 1 FROM product_images
                WHERE product_images.product_id = products.id
              )
        """))

        # ✅ Also backfill from image_url column if product_images has nothing
        # This covers products where image_url was set but product_images table was not populated
        db.execute(text("""
            UPDATE products
            SET main_image = image_url
            WHERE (main_image IS NULL OR main_image = '')
              AND (image_url IS NOT NULL AND image_url != '')
        """))

        # ✅ Backfill is_primary — mark first image (position=0) as primary
        # for all products where no image is marked primary yet
        db.execute(text("""
            UPDATE product_images pi
            SET is_primary = TRUE
            FROM (
                SELECT DISTINCT ON (product_id) id
                FROM product_images
                ORDER BY product_id, position ASC
            ) first_imgs
            WHERE pi.id = first_imgs.id
              AND pi.is_primary = FALSE
              AND NOT EXISTS (
                SELECT 1 FROM product_images pi2
                WHERE pi2.product_id = pi.product_id
                  AND pi2.is_primary = TRUE
              )
        """))

        db.commit()
        print("✅ Database schema verified")
        print("🚀 Enterprise features initialized")
        print("🏠 Homepage sections → GET /api/homepage/sections")
    except Exception as e:
        print("❌ Startup migration failed:", e)
    finally:
        db.close()