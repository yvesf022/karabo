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
from app.routes import auto_pricing                             # ← AI Auto-Pricer (server-side Anthropic)
from app.routes import bulk_price_update                        # ← One-time bulk price update


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

# ══ STATIC-PATH ROUTERS FIRST — must register before any router with /{id} ══
# random_products has /products/random — must come before products.router (/{product_id})
app.include_router(random_products.router,      prefix="/api")
# categories_router has /categories/departments — must come before categories_brands (/{category_id})
app.include_router(categories_router.router,    prefix="/api")
# homepage_sections has /homepage/sections — no conflict but register early for safety
app.include_router(homepage_sections.router,    prefix="/api")

# auto_pricing has /products/admin/auto-price/... — must come before products.router (/{product_id})
app.include_router(auto_pricing.router,         prefix="/api")

# bulk_price_update — one-time price migration endpoint
app.include_router(bulk_price_update.router,    prefix="/api")

# ── Core routers with dynamic /{id} routes ────────────────────────────────────
app.include_router(products.router,        prefix="/api")
app.include_router(orders.router,          prefix="/api")
app.include_router(payments.router,        prefix="/api")
app.include_router(admin.router,           prefix="/api")
app.include_router(admin_users.router,     prefix="/api")
app.include_router(password_reset.router,  prefix="/api")

# ── Enterprise — User ──────────────────────────────────────────────────────────
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

# ── Enterprise — Admin ─────────────────────────────────────────────────────────
app.include_router(admin_orders_advanced.router,   prefix="/api")
app.include_router(admin_payments_advanced.router,  prefix="/api")
app.include_router(admin_users_advanced.router,     prefix="/api")

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

        # ✅ Add pricing workflow columns if missing
        db.execute(text(
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS pricing_status "
            "VARCHAR NOT NULL DEFAULT 'unpriced'"
        ))
        db.execute(text(
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS priced_by "
            "UUID REFERENCES users(id) ON DELETE SET NULL"
        ))
        # ✅ Backfill pricing_status for products already marked as priced
        db.execute(text("""
            UPDATE products
            SET pricing_status = 'admin_approved'
            WHERE is_priced = TRUE
              AND (pricing_status IS NULL OR pricing_status = 'unpriced')
        """))

        # ✅ CATEGORY BACKFILL — normalize all dirty category values to clean slugs.
        # Runs on every startup but the WHERE clause skips already-clean products,
        # so it's a no-op once all rows are normalised.
        # Maps known variants → canonical slug; anything unrecognised → 'others'.
        db.execute(text("""
            UPDATE products
            SET category = CASE
                LOWER(TRIM(REPLACE(REPLACE(COALESCE(category, ''), '-', '_'), ' ', '_')))
                WHEN 'anti_aging'           THEN 'anti_aging'
                WHEN 'antiaging'            THEN 'anti_aging'
                WHEN 'acne'                 THEN 'acne'
                WHEN 'brightening'          THEN 'brightening'
                WHEN 'whitening'            THEN 'whitening'
                WHEN 'hydration'            THEN 'hydration'
                WHEN 'repair'               THEN 'repair'
                WHEN 'barrier'              THEN 'barrier'
                WHEN 'eczema'               THEN 'eczema'
                WHEN 'rosacea'              THEN 'rosacea'
                WHEN 'scar'                 THEN 'scar'
                WHEN 'stretch_mark'         THEN 'stretch_mark'
                WHEN 'stretch_marks'        THEN 'stretch_mark'
                WHEN 'sunscreen'            THEN 'sunscreen'
                WHEN 'oils'                 THEN 'oils'
                WHEN 'soaps'                THEN 'soaps'
                WHEN 'body'                 THEN 'body'
                WHEN 'masks'                THEN 'masks'
                WHEN 'exfoliation'          THEN 'exfoliation'
                WHEN 'exfoliator'           THEN 'exfoliation'
                WHEN 'clinical_acids'       THEN 'clinical_acids'
                WHEN 'african_ingredients'  THEN 'african_ingredients'
                WHEN 'african'              THEN 'african_ingredients'
                WHEN 'korean_ingredients'   THEN 'korean_ingredients'
                WHEN 'korean'               THEN 'korean_ingredients'
                WHEN 'others'               THEN 'others'
                ELSE 'others'
            END
            WHERE category IS NULL
               OR TRIM(category) = ''
               OR category NOT IN (
                   'anti_aging','acne','brightening','whitening','hydration',
                   'repair','barrier','eczema','rosacea','scar','stretch_mark',
                   'sunscreen','oils','soaps','body','masks','exfoliation',
                   'clinical_acids','african_ingredients','korean_ingredients','others'
               )
        """))
        print("✅ Category slugs backfilled")

        db.commit()
        print("✅ Database schema verified")
        print("🚀 Enterprise features initialized")
        print("🏠 Homepage sections → GET /api/homepage/sections")
    except Exception as e:
        print("❌ Startup migration failed:", e)
    finally:
        db.close()