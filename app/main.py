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

        db.execute(text("""
            UPDATE products
            SET main_image = image_url
            WHERE (main_image IS NULL OR main_image = '')
              AND (image_url IS NOT NULL AND image_url != '')
        """))

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

        # ══════════════════════════════════════════════════════════════════
        # 🔥 BULK AUTO-PRICING — runs on startup, skips already-priced
        # All prices researched from Amazon.in / Flipkart / Nykaa Feb 2026
        # Formula: (market_INR + 700 shipping + 500 profit) × 0.21
        #          rounded to nearest M0.50 | compare = price × 1.30
        # Safe to run every deploy — only touches is_priced = FALSE rows
        # ══════════════════════════════════════════════════════════════════
        _run_bulk_pricing(db)

    except Exception as e:
        print("❌ Startup migration failed:", e)
    finally:
        db.close()


def _run_bulk_pricing(db):
    """
    Prices every unpriced product using real India market data.
    Matched by brand keyword within category — most specific first,
    then brand default, then category default, then absolute fallback.
    Safe: only updates rows where is_priced = FALSE.
    """
    try:
        unpriced = db.execute(text(
            "SELECT COUNT(*) FROM products WHERE is_deleted=FALSE AND is_priced=FALSE"
        )).scalar()

        if unpriced == 0:
            print("💰 All products already priced — skipping bulk pricer")
            return

        print(f"💰 Bulk pricer starting — {unpriced} unpriced products...")

        RATE = 0.21  # INR → LSL  (live rate Feb 26 2026)

        def upd(keyword, category, inr):
            """Update products in category whose title contains keyword."""
            total  = inr + 700 + 500
            final  = round(total * RATE * 2) / 2
            compare = round(final * 1.30, 2)
            safe_kw = keyword.replace("'", "''")
            db.execute(text(f"""
                UPDATE products
                SET price         = {final},
                    compare_price = {compare},
                    is_priced     = TRUE,
                    priced_at     = NOW()
                WHERE is_deleted  = FALSE
                  AND is_priced   = FALSE
                  AND category    = '{category}'
                  AND LOWER(title) LIKE LOWER('%{safe_kw}%')
            """))

        def cat_default(category, inr):
            """Price everything still unpriced in a category."""
            total  = inr + 700 + 500
            final  = round(total * RATE * 2) / 2
            compare = round(final * 1.30, 2)
            db.execute(text(f"""
                UPDATE products
                SET price         = {final},
                    compare_price = {compare},
                    is_priced     = TRUE,
                    priced_at     = NOW()
                WHERE is_deleted = FALSE
                  AND is_priced  = FALSE
                  AND category   = '{category}'
            """))

        # ── SUNSCREEN ────────────────────────────────────────────────────
        upd("Neutrogena Ultra Sheer SPF 50+ 88ml", "sunscreen", 880)
        upd("Neutrogena Ultra Sheer", "sunscreen", 624)
        upd("Neutrogena", "sunscreen", 699)
        upd("Minimalist SPF 60", "sunscreen", 499)
        upd("Minimalist SPF 50", "sunscreen", 399)
        upd("Minimalist Light Fluid", "sunscreen", 499)
        upd("Minimalist", "sunscreen", 399)
        upd("The Derma Co Hyaluronic Sunscreen", "sunscreen", 349)
        upd("The Derma Co", "sunscreen", 395)
        upd("Mamaearth HydraGel", "sunscreen", 399)
        upd("Mamaearth Vitamin C Sunscreen", "sunscreen", 349)
        upd("Mamaearth", "sunscreen", 399)
        upd("Lotus Herbals Safe Sun SPF 70", "sunscreen", 595)
        upd("Lotus Herbals", "sunscreen", 499)
        upd("Lakme Sun Expert SPF 50", "sunscreen", 345)
        upd("Lakme", "sunscreen", 345)
        upd("Dot & Key Waterlight", "sunscreen", 595)
        upd("Dot & Key Vitamin C + E Sunscreen", "sunscreen", 445)
        upd("Dot & Key Mango", "sunscreen", 445)
        upd("Dot & Key", "sunscreen", 495)
        upd("Beauty of Joseon", "sunscreen", 1570)
        upd("Plum", "sunscreen", 595)
        upd("Re'equil", "sunscreen", 595)
        upd("Bioderma Photoderm", "sunscreen", 999)
        upd("La Roche-Posay", "sunscreen", 1800)
        upd("Cetaphil", "sunscreen", 799)
        upd("WOW Skin", "sunscreen", 399)
        upd("Himalaya", "sunscreen", 175)
        upd("Garnier", "sunscreen", 299)
        upd("L'Oreal", "sunscreen", 549)
        upd("Nivea", "sunscreen", 399)
        cat_default("sunscreen", 450)

        # ── MOISTURIZER ──────────────────────────────────────────────────
        upd("CeraVe PM Facial Moisturizer", "moisturizer", 1300)
        upd("CeraVe AM Facial Moisturizing Lotion", "moisturizer", 1500)
        upd("CeraVe Moisturizer Cream", "moisturizer", 430)
        upd("CeraVe Oil Control", "moisturizer", 1200)
        upd("CeraVe", "moisturizer", 850)
        upd("Neutrogena Hydro Boost Water Gel", "moisturizer", 1190)
        upd("Neutrogena", "moisturizer", 799)
        upd("Minimalist Vitamin B5", "moisturizer", 349)
        upd("Minimalist Marula Oil", "moisturizer", 299)
        upd("Minimalist", "moisturizer", 349)
        upd("The Ordinary Natural Moisturising Factors", "moisturizer", 875)
        upd("The Ordinary", "moisturizer", 699)
        upd("Mamaearth Vitamin C Oil-Free", "moisturizer", 319)
        upd("Mamaearth Beetroot", "moisturizer", 449)
        upd("Mamaearth Tea Tree", "moisturizer", 319)
        upd("Mamaearth", "moisturizer", 349)
        upd("Plum Green Tea Oil-Free Moisturizer", "moisturizer", 450)
        upd("Plum", "moisturizer", 450)
        upd("Simple Kind to Skin", "moisturizer", 320)
        upd("Simple", "moisturizer", 320)
        upd("Cetaphil", "moisturizer", 499)
        upd("Bioderma", "moisturizer", 899)
        upd("La Roche-Posay", "moisturizer", 1699)
        upd("Olay", "moisturizer", 799)
        upd("Ponds", "moisturizer", 225)
        upd("Pond's", "moisturizer", 225)
        upd("Himalaya", "moisturizer", 199)
        upd("Garnier", "moisturizer", 299)
        upd("WOW Skin", "moisturizer", 449)
        upd("Dot & Key", "moisturizer", 595)
        upd("MCaffeine", "moisturizer", 399)
        upd("Pilgrim", "moisturizer", 499)
        cat_default("moisturizer", 399)

        # ── FACE WASH ────────────────────────────────────────────────────
        upd("CeraVe SA Smoothing Cleanser", "face_wash", 1250)
        upd("CeraVe Blemish Control Cleanser", "face_wash", 1250)
        upd("CeraVe Foaming Cleanser", "face_wash", 520)
        upd("CeraVe Hydrating Cleanser", "face_wash", 330)
        upd("CeraVe", "face_wash", 680)
        upd("Minimalist 2% Salicylic Acid", "face_wash", 299)
        upd("Minimalist 6% Oat Extract", "face_wash", 299)
        upd("Minimalist", "face_wash", 299)
        upd("Neutrogena Oil-Free Acne Face Wash", "face_wash", 850)
        upd("Neutrogena", "face_wash", 699)
        upd("Mamaearth Vitamin C Face Wash", "face_wash", 269)
        upd("Mamaearth Rice Face Wash", "face_wash", 269)
        upd("Mamaearth Tea Tree", "face_wash", 269)
        upd("Mamaearth Ubtan", "face_wash", 269)
        upd("Mamaearth", "face_wash", 269)
        upd("Simple Refreshing Facial Wash", "face_wash", 420)
        upd("Simple Kind to Skin", "face_wash", 420)
        upd("Simple", "face_wash", 420)
        upd("Himalaya Purifying Neem", "face_wash", 155)
        upd("Himalaya", "face_wash", 175)
        upd("Lakme Blush & Glow", "face_wash", 155)
        upd("Lakme", "face_wash", 185)
        upd("Garnier Bright Complete", "face_wash", 189)
        upd("Garnier", "face_wash", 225)
        upd("Plum", "face_wash", 349)
        upd("MCaffeine", "face_wash", 299)
        upd("Cetaphil", "face_wash", 499)
        upd("WOW Skin", "face_wash", 349)
        upd("Dove", "face_wash", 225)
        upd("Olay", "face_wash", 599)
        upd("L'Oreal", "face_wash", 349)
        upd("COSRX", "face_wash", 799)
        upd("Dot & Key", "face_wash", 395)
        upd("Pilgrim", "face_wash", 299)
        upd("Ponds", "face_wash", 175)
        upd("Pond's", "face_wash", 175)
        cat_default("face_wash", 249)

        # ── SERUM ────────────────────────────────────────────────────────
        upd("Minimalist 10% Niacinamide", "serum", 599)
        upd("Minimalist Niacinamide 05%", "serum", 599)
        upd("Minimalist 16% Vitamin C", "serum", 799)
        upd("Minimalist 10% Vitamin C", "serum", 299)
        upd("Minimalist 2% Salicylic Acid Face Serum", "serum", 549)
        upd("Minimalist 2% Alpha Arbutin", "serum", 549)
        upd("Minimalist 3% Tranexamic", "serum", 599)
        upd("Minimalist Retinol 0.3%", "serum", 599)
        upd("Minimalist Multi Peptide", "serum", 699)
        upd("Minimalist Hyaluronic Acid 2%", "serum", 599)
        upd("Minimalist", "serum", 549)
        upd("The Ordinary Niacinamide 10%", "serum", 590)
        upd("The Ordinary Hyaluronic Acid 2%", "serum", 699)
        upd("The Ordinary Retinol", "serum", 875)
        upd("The Ordinary Glycolic Acid", "serum", 1275)
        upd("The Ordinary Buffet", "serum", 1650)
        upd("The Ordinary", "serum", 699)
        upd("Mamaearth Vitamin C Face Serum", "serum", 499)
        upd("Mamaearth Skin Illuminate", "serum", 499)
        upd("Mamaearth", "serum", 449)
        upd("The Derma Co 10% Vitamin C", "serum", 695)
        upd("The Derma Co Hyaluronic", "serum", 595)
        upd("The Derma Co", "serum", 595)
        upd("Plum 15% Vitamin C", "serum", 775)
        upd("Plum", "serum", 695)
        upd("Dot & Key 20% Vitamin C", "serum", 879)
        upd("Dot & Key", "serum", 795)
        upd("Pilgrim", "serum", 649)
        upd("MCaffeine", "serum", 499)
        upd("WOW Skin", "serum", 499)
        upd("COSRX", "serum", 999)
        upd("L'Oreal Revitalift", "serum", 799)
        upd("L'Oreal", "serum", 699)
        upd("Olay", "serum", 999)
        upd("Kiehl's", "serum", 2750)
        upd("La Roche-Posay", "serum", 1999)
        upd("Cetaphil", "serum", 899)
        cat_default("serum", 599)

        # ── BODY LOTION ──────────────────────────────────────────────────
        upd("CeraVe Moisturizing Body Lotion", "body_lotion", 1750)
        upd("CeraVe", "body_lotion", 1750)
        upd("The Ordinary Natural Moisturising Body", "body_lotion", 999)
        upd("The Ordinary", "body_lotion", 875)
        upd("Mamaearth Vitamin C Daily Glow Body Lotion", "body_lotion", 499)
        upd("Mamaearth Ubtan Body Lotion", "body_lotion", 549)
        upd("Mamaearth", "body_lotion", 499)
        upd("Vaseline Deep Moisture", "body_lotion", 475)
        upd("Vaseline", "body_lotion", 399)
        upd("Nivea Body Milk", "body_lotion", 399)
        upd("Nivea", "body_lotion", 399)
        upd("Lakme Peach Milk", "body_lotion", 349)
        upd("Lakme", "body_lotion", 349)
        upd("WOW Skin", "body_lotion", 499)
        upd("MCaffeine", "body_lotion", 449)
        upd("Dove", "body_lotion", 399)
        upd("Ponds", "body_lotion", 325)
        upd("Pond's", "body_lotion", 325)
        upd("Plum", "body_lotion", 595)
        upd("Pilgrim", "body_lotion", 499)
        upd("Biotique", "body_lotion", 299)
        upd("Himalaya", "body_lotion", 225)
        upd("Garnier", "body_lotion", 299)
        cat_default("body_lotion", 449)

        # ── FACE MASK ────────────────────────────────────────────────────
        upd("MCaffeine Coffee Clay", "face_mask", 399)
        upd("MCaffeine", "face_mask", 399)
        upd("Mamaearth Charcoal", "face_mask", 349)
        upd("Mamaearth Ubtan Detan", "face_mask", 499)
        upd("Mamaearth", "face_mask", 349)
        upd("WOW Skin Science Red Clay", "face_mask", 499)
        upd("WOW Skin", "face_mask", 449)
        upd("The Moms Co Natural Clay", "face_mask", 399)
        upd("Plum Green Tea Pore-Cleansing", "face_mask", 595)
        upd("Plum", "face_mask", 495)
        upd("Kama Ayurveda", "face_mask", 795)
        upd("O3+", "face_mask", 999)
        upd("Dot & Key", "face_mask", 595)
        upd("Minimalist", "face_mask", 599)
        upd("Pilgrim", "face_mask", 399)
        upd("Himalaya", "face_mask", 175)
        upd("Garnier", "face_mask", 199)
        upd("Biotique", "face_mask", 249)
        cat_default("face_mask", 399)

        # ── EYE MASK ─────────────────────────────────────────────────────
        upd("Kiehl's", "eye_mask", 2750)
        upd("Laneige", "eye_mask", 1799)
        upd("Minimalist", "eye_mask", 499)
        upd("Dot & Key Vitamin C + E Under Eye", "eye_mask", 395)
        upd("Dot & Key", "eye_mask", 595)
        upd("Pilgrim Retinol Eye", "eye_mask", 499)
        upd("Pilgrim", "eye_mask", 499)
        upd("Just Herbs", "eye_mask", 595)
        upd("mCaffeine", "eye_mask", 499)
        upd("MCaffeine", "eye_mask", 499)
        upd("Plum", "eye_mask", 695)
        upd("WOW Skin", "eye_mask", 499)
        upd("Mamaearth", "eye_mask", 449)
        upd("The Ordinary", "eye_mask", 699)
        upd("Olay", "eye_mask", 999)
        upd("COSRX", "eye_mask", 799)
        cat_default("eye_mask", 499)

        # ── ANTI ACNE ────────────────────────────────────────────────────
        upd("Minimalist 2% Salicylic Acid Serum", "anti_acne", 549)
        upd("Minimalist", "anti_acne", 549)
        upd("COSRX Acne Pimple Master Patch", "anti_acne", 699)
        upd("COSRX", "anti_acne", 799)
        upd("The Derma Co 2% Salicylic", "anti_acne", 595)
        upd("The Derma Co", "anti_acne", 595)
        upd("Neutrogena Rapid Clear", "anti_acne", 699)
        upd("Neutrogena", "anti_acne", 599)
        upd("Mamaearth Tea Tree Anti-Acne", "anti_acne", 349)
        upd("Mamaearth", "anti_acne", 399)
        upd("WOW Skin", "anti_acne", 399)
        upd("Plum", "anti_acne", 499)
        upd("Pilgrim", "anti_acne", 449)
        upd("Dot & Key", "anti_acne", 595)
        upd("CeraVe", "anti_acne", 850)
        upd("Himalaya", "anti_acne", 175)
        upd("Garnier", "anti_acne", 249)
        cat_default("anti_acne", 449)

        # ── SKIN BRIGHTENING ─────────────────────────────────────────────
        upd("Minimalist 2% Alpha Arbutin", "skin_brightening", 549)
        upd("Minimalist 3% Tranexamic", "skin_brightening", 599)
        upd("Minimalist 16% Vitamin C", "skin_brightening", 799)
        upd("Minimalist", "skin_brightening", 549)
        upd("Dot & Key Vitamin C + E Super Bright", "skin_brightening", 879)
        upd("Dot & Key", "skin_brightening", 795)
        upd("Mamaearth Skin Illuminate", "skin_brightening", 499)
        upd("Mamaearth Vitamin C", "skin_brightening", 499)
        upd("Mamaearth", "skin_brightening", 499)
        upd("Lakme Absolute Perfect Radiance", "skin_brightening", 499)
        upd("Lakme", "skin_brightening", 499)
        upd("L'Oreal Paris Revitalift Brightening", "skin_brightening", 799)
        upd("L'Oreal", "skin_brightening", 699)
        upd("Plum Bright Years", "skin_brightening", 775)
        upd("Plum", "skin_brightening", 695)
        upd("Pilgrim", "skin_brightening", 649)
        upd("The Derma Co", "skin_brightening", 695)
        upd("The Ordinary", "skin_brightening", 875)
        upd("MCaffeine", "skin_brightening", 499)
        upd("Olay", "skin_brightening", 999)
        upd("WOW Skin", "skin_brightening", 499)
        cat_default("skin_brightening", 599)

        # ── COLLAGEN ─────────────────────────────────────────────────────
        upd("Neutrogena Rapid Wrinkle Repair Retinol Cream", "collagen", 1299)
        upd("Neutrogena", "collagen", 999)
        upd("Mamaearth Collagen Anti-Aging", "collagen", 699)
        upd("Mamaearth", "collagen", 699)
        upd("WOW Skin Anti-Aging Collagen", "collagen", 599)
        upd("WOW Skin", "collagen", 599)
        upd("Olay Regenerist", "collagen", 1299)
        upd("Olay", "collagen", 999)
        upd("Minimalist Multi Peptide", "collagen", 699)
        upd("Minimalist", "collagen", 699)
        upd("The Ordinary", "collagen", 875)
        upd("Plum", "collagen", 775)
        upd("Pilgrim", "collagen", 649)
        upd("Dot & Key", "collagen", 879)
        cat_default("collagen", 699)

        # ── SKIN NATURAL OILS ────────────────────────────────────────────
        upd("Kama Ayurveda Rose Hip Seed Oil", "skin_natural_oils", 695)
        upd("Kama Ayurveda", "skin_natural_oils", 895)
        upd("Mamaearth Rosehip Oil", "skin_natural_oils", 549)
        upd("Mamaearth", "skin_natural_oils", 499)
        upd("WOW Skin Science Jojoba Oil", "skin_natural_oils", 499)
        upd("WOW Skin", "skin_natural_oils", 499)
        upd("Pilgrim Sea Buckthorn", "skin_natural_oils", 649)
        upd("Pilgrim", "skin_natural_oils", 649)
        upd("The Ordinary", "skin_natural_oils", 875)
        upd("Forest Essentials", "skin_natural_oils", 1195)
        upd("Plum", "skin_natural_oils", 695)
        upd("Minimalist", "skin_natural_oils", 499)
        upd("Biotique", "skin_natural_oils", 299)
        cat_default("skin_natural_oils", 549)

        # ── HERBAL OILS ──────────────────────────────────────────────────
        upd("Forest Essentials Nirgundi", "herbal_oils", 1195)
        upd("Forest Essentials", "herbal_oils", 1195)
        upd("Kama Ayurveda Pure Sesame", "herbal_oils", 795)
        upd("Kama Ayurveda", "herbal_oils", 895)
        upd("Biotique Bio Henna", "herbal_oils", 225)
        upd("Biotique", "herbal_oils", 249)
        upd("Indulekha Bringha", "herbal_oils", 499)
        upd("Indulekha", "herbal_oils", 499)
        upd("Mamaearth Rosemary", "herbal_oils", 349)
        upd("Mamaearth Onion", "herbal_oils", 299)
        upd("Mamaearth", "herbal_oils", 349)
        upd("WOW Skin", "herbal_oils", 449)
        upd("Himalaya", "herbal_oils", 225)
        upd("Dabur", "herbal_oils", 299)
        upd("Parachute", "herbal_oils", 199)
        cat_default("herbal_oils", 399)

        # ── ANTI WRINKLES ────────────────────────────────────────────────
        upd("Neutrogena Rapid Wrinkle Repair Night Cream", "anti_wrinkles", 1599)
        upd("Neutrogena Rapid Wrinkle Repair", "anti_wrinkles", 1299)
        upd("Neutrogena", "anti_wrinkles", 999)
        upd("The Ordinary Retinol 0.5%", "anti_wrinkles", 875)
        upd("The Ordinary", "anti_wrinkles", 699)
        upd("Minimalist Retinal 0.2%", "anti_wrinkles", 949)
        upd("Minimalist 0.3% Retinol", "anti_wrinkles", 599)
        upd("Minimalist 2% Granactive Retinoid", "anti_wrinkles", 599)
        upd("Minimalist", "anti_wrinkles", 699)
        upd("Olay Total Effects 7-in-1", "anti_wrinkles", 999)
        upd("Olay Regenerist", "anti_wrinkles", 1499)
        upd("Olay", "anti_wrinkles", 999)
        upd("L'Oreal Paris Revitalift Anti-Wrinkle", "anti_wrinkles", 799)
        upd("L'Oreal", "anti_wrinkles", 699)
        upd("Mamaearth Collagen", "anti_wrinkles", 699)
        upd("Mamaearth", "anti_wrinkles", 549)
        upd("Plum Bright Years", "anti_wrinkles", 775)
        upd("Plum", "anti_wrinkles", 695)
        upd("Dot & Key", "anti_wrinkles", 879)
        upd("Pilgrim", "anti_wrinkles", 649)
        upd("La Roche-Posay", "anti_wrinkles", 2499)
        upd("Kiehl's", "anti_wrinkles", 3499)
        cat_default("anti_wrinkles", 875)

        # ── BODY WASH ────────────────────────────────────────────────────
        upd("Dove Deeply Nourishing", "body_wash", 349)
        upd("Dove", "body_wash", 349)
        upd("MCaffeine Coffee Body Wash", "body_wash", 399)
        upd("MCaffeine", "body_wash", 399)
        upd("Mamaearth Vitamin C Body Wash", "body_wash", 349)
        upd("Mamaearth", "body_wash", 349)
        upd("WOW Skin Science Coconut Milk", "body_wash", 399)
        upd("WOW Skin", "body_wash", 399)
        upd("Biotique Morning Nectar", "body_wash", 249)
        upd("Biotique", "body_wash", 249)
        upd("Fiama Gel Bar", "body_wash", 265)
        upd("Fiama", "body_wash", 265)
        upd("Plum", "body_wash", 449)
        upd("Himalaya", "body_wash", 199)
        upd("Nivea", "body_wash", 349)
        upd("Pears", "body_wash", 225)
        upd("Lifebuoy", "body_wash", 199)
        upd("Dettol", "body_wash", 225)
        upd("Palmolive", "body_wash", 299)
        upd("Forest Essentials", "body_wash", 995)
        upd("Pilgrim", "body_wash", 349)
        upd("Kama Ayurveda", "body_wash", 695)
        cat_default("body_wash", 299)

        # ── EXFOLIATOR ───────────────────────────────────────────────────
        upd("Minimalist AHA 25% + BHA 2%", "exfoliator", 799)
        upd("Minimalist Lactic Acid 10%", "exfoliator", 599)
        upd("Minimalist 8% Glycolic Acid", "exfoliator", 499)
        upd("Minimalist", "exfoliator", 599)
        upd("The Ordinary Glycolic Acid 7%", "exfoliator", 1275)
        upd("The Ordinary AHA 30%", "exfoliator", 1499)
        upd("The Ordinary", "exfoliator", 999)
        upd("MCaffeine Coffee Face Scrub", "exfoliator", 299)
        upd("MCaffeine", "exfoliator", 349)
        upd("Mamaearth Ubtan Face Scrub", "exfoliator", 299)
        upd("Mamaearth", "exfoliator", 299)
        upd("WOW Skin Science Brightening Vitamin C Scrub", "exfoliator", 399)
        upd("WOW Skin", "exfoliator", 399)
        upd("St.Ives Fresh Skin Apricot", "exfoliator", 399)
        upd("St. Ives", "exfoliator", 399)
        upd("Plum", "exfoliator", 595)
        upd("Dot & Key", "exfoliator", 695)
        upd("Pilgrim", "exfoliator", 499)
        upd("Himalaya", "exfoliator", 175)
        upd("COSRX", "exfoliator", 799)
        upd("Biotique", "exfoliator", 199)
        cat_default("exfoliator", 399)

        # ── LIP MASK ─────────────────────────────────────────────────────
        upd("Laneige Lip Sleeping Mask", "lip_mask", 1799)
        upd("Laneige", "lip_mask", 1799)
        upd("The Ordinary Hyaluronic Acid Lip", "lip_mask", 799)
        upd("The Ordinary", "lip_mask", 699)
        upd("Minimalist", "lip_mask", 299)
        upd("Mamaearth Vitamin C Lip Balm", "lip_mask", 199)
        upd("Mamaearth Beetroot Tinted Lip", "lip_mask", 299)
        upd("Mamaearth", "lip_mask", 249)
        upd("Plum E-Luminence", "lip_mask", 295)
        upd("Plum", "lip_mask", 295)
        upd("Nykaa Lip Love", "lip_mask", 225)
        upd("Nykaa", "lip_mask", 225)
        upd("MCaffeine", "lip_mask", 299)
        upd("Dot & Key", "lip_mask", 395)
        upd("Pilgrim", "lip_mask", 299)
        upd("WOW Skin", "lip_mask", 299)
        cat_default("lip_mask", 299)

        # ── SAMSUNG ──────────────────────────────────────────────────────
        upd("Galaxy S25 Ultra", "samsung", 134999)
        upd("Galaxy S25+", "samsung", 99999)
        upd("Galaxy S25", "samsung", 80999)
        upd("Galaxy S24 Ultra", "samsung", 129999)
        upd("Galaxy S24+", "samsung", 99999)
        upd("Galaxy S24 FE", "samsung", 44999)
        upd("Galaxy S24", "samsung", 59999)
        upd("Galaxy S23 Ultra", "samsung", 84999)
        upd("Galaxy S23", "samsung", 54999)
        upd("Galaxy A56", "samsung", 31999)
        upd("Galaxy A55", "samsung", 27999)
        upd("Galaxy A35", "samsung", 20000)
        upd("Galaxy A16", "samsung", 14999)
        upd("Galaxy A15", "samsung", 12999)
        upd("Galaxy M35", "samsung", 17000)
        upd("Galaxy M15", "samsung", 11999)
        upd("Galaxy F55", "samsung", 22999)
        upd("Galaxy F15", "samsung", 12499)
        upd("Galaxy A06", "samsung", 11999)
        upd("Galaxy A05s", "samsung", 9999)
        upd("Galaxy A05", "samsung", 8999)
        upd("Galaxy M55", "samsung", 25999)
        upd("Galaxy Z Fold", "samsung", 164999)
        upd("Galaxy Z Flip", "samsung", 99999)
        upd("Galaxy Tab S9", "samsung", 72999)
        upd("Galaxy Tab S8", "samsung", 54999)
        upd("Galaxy Tab A9", "samsung", 17999)
        cat_default("samsung", 18000)

        # ── APPLE ────────────────────────────────────────────────────────
        upd("iPhone 16 Pro Max", "apple", 159900)
        upd("iPhone 16 Pro", "apple", 119900)
        upd("iPhone 16 Plus", "apple", 89900)
        upd("iPhone 16", "apple", 69900)
        upd("iPhone 15 Pro Max", "apple", 159900)
        upd("iPhone 15 Pro", "apple", 119900)
        upd("iPhone 15 Plus", "apple", 64900)
        upd("iPhone 15", "apple", 54790)
        upd("iPhone 14 Plus", "apple", 54900)
        upd("iPhone 14", "apple", 45900)
        upd("iPhone 13", "apple", 39900)
        upd("iPhone SE", "apple", 59900)
        upd("iPhone 12", "apple", 33900)
        upd("iPad Pro", "apple", 89900)
        upd("iPad Air", "apple", 59900)
        upd("iPad mini", "apple", 46900)
        upd("iPad", "apple", 37900)
        upd("Apple Watch Ultra", "apple", 89900)
        upd("Apple Watch Series", "apple", 41900)
        upd("AirPods Pro", "apple", 24900)
        upd("AirPods", "apple", 13900)
        cat_default("apple", 54000)

        # ── XIAOMI / REDMI / POCO ────────────────────────────────────────
        upd("Xiaomi 14 Ultra", "xiaomi", 99999)
        upd("Xiaomi 14", "xiaomi", 59999)
        upd("Redmi Note 15 Pro+", "xiaomi", 29999)
        upd("Redmi Note 15 Pro", "xiaomi", 24999)
        upd("Redmi Note 15", "xiaomi", 22998)
        upd("Redmi Note 14 Pro+", "xiaomi", 26999)
        upd("Redmi Note 14 Pro", "xiaomi", 22999)
        upd("Redmi Note 14 SE", "xiaomi", 13999)
        upd("Redmi Note 14", "xiaomi", 13999)
        upd("Redmi Note 13 Pro+", "xiaomi", 26999)
        upd("Redmi Note 13 Pro", "xiaomi", 22999)
        upd("Redmi Note 13", "xiaomi", 16999)
        upd("Redmi 15", "xiaomi", 14999)
        upd("Redmi 14C", "xiaomi", 9499)
        upd("Redmi 14", "xiaomi", 11999)
        upd("Redmi 13C", "xiaomi", 8499)
        upd("Redmi 13", "xiaomi", 9999)
        upd("Redmi 12", "xiaomi", 9499)
        upd("Redmi A3", "xiaomi", 7499)
        upd("Redmi A2", "xiaomi", 6999)
        upd("Poco X7 Pro", "xiaomi", 26999)
        upd("Poco X7", "xiaomi", 19999)
        upd("Poco X6 Pro", "xiaomi", 23999)
        upd("Poco X6", "xiaomi", 18999)
        upd("Poco M7 Pro", "xiaomi", 14999)
        upd("Poco M7", "xiaomi", 12499)
        upd("Poco M6 Pro", "xiaomi", 10999)
        upd("Poco M6", "xiaomi", 9499)
        upd("Poco F6 Pro", "xiaomi", 49999)
        upd("Poco F6", "xiaomi", 29999)
        upd("Poco C75", "xiaomi", 9999)
        upd("Poco C65", "xiaomi", 8499)
        upd("Poco C61", "xiaomi", 7499)
        cat_default("xiaomi", 13999)

        # ── MOTOROLA ─────────────────────────────────────────────────────
        upd("Moto Edge 70 Pro", "motorola", 35999)
        upd("Moto Edge 70 Fusion", "motorola", 20900)
        upd("Moto Edge 70", "motorola", 30457)
        upd("Moto Edge 60 Pro", "motorola", 28449)
        upd("Moto Edge 60 Fusion", "motorola", 20900)
        upd("Moto Edge 60", "motorola", 23999)
        upd("Moto Edge 50 Fusion", "motorola", 18999)
        upd("Moto Edge 50 Pro", "motorola", 31999)
        upd("Moto Edge 50", "motorola", 22999)
        upd("Moto G85", "motorola", 15999)
        upd("Moto G75", "motorola", 18999)
        upd("Moto G65", "motorola", 13999)
        upd("Moto G64", "motorola", 13999)
        upd("Moto G55", "motorola", 12999)
        upd("Moto G45", "motorola", 11999)
        upd("Moto G35", "motorola", 10999)
        upd("Moto G34", "motorola", 9999)
        upd("Moto G24 Power", "motorola", 9999)
        upd("Moto G24", "motorola", 8999)
        upd("Moto G14", "motorola", 7999)
        upd("Moto G04", "motorola", 6499)
        upd("Moto E14", "motorola", 5999)
        upd("Moto E13", "motorola", 5499)
        cat_default("motorola", 14999)

        # ── ONEPLUS ──────────────────────────────────────────────────────
        upd("OnePlus 15R", "oneplus", 47998)
        upd("OnePlus 15", "oneplus", 72997)
        upd("OnePlus 13", "oneplus", 64999)
        upd("OnePlus 12R", "oneplus", 36999)
        upd("OnePlus 12", "oneplus", 64999)
        upd("OnePlus 11", "oneplus", 49999)
        upd("OnePlus Nord 5", "oneplus", 33999)
        upd("OnePlus Nord 4", "oneplus", 29999)
        upd("OnePlus Nord CE4 Lite", "oneplus", 18195)
        upd("OnePlus Nord CE4", "oneplus", 24999)
        upd("OnePlus Nord CE3 Lite", "oneplus", 16999)
        upd("OnePlus Nord CE3", "oneplus", 24999)
        upd("OnePlus Nord CE2 Lite", "oneplus", 14999)
        upd("OnePlus Nord CE2", "oneplus", 22999)
        upd("OnePlus Open", "oneplus", 149999)
        cat_default("oneplus", 27999)

        # ── GOOGLE PIXEL ─────────────────────────────────────────────────
        upd("Pixel 9 Pro XL", "google", 109999)
        upd("Pixel 9 Pro Fold", "google", 172000)
        upd("Pixel 9 Pro", "google", 88990)
        upd("Pixel 9A", "google", 38450)
        upd("Pixel 9", "google", 74999)
        upd("Pixel 8 Pro", "google", 79999)
        upd("Pixel 8A", "google", 34999)
        upd("Pixel 8", "google", 59999)
        upd("Pixel 7A", "google", 34999)
        upd("Pixel 7 Pro", "google", 59999)
        upd("Pixel 7", "google", 44999)
        upd("Pixel 6A", "google", 29999)
        cat_default("google", 59999)

        # ── REALME ───────────────────────────────────────────────────────
        upd("realme GT 8 Pro", "realme", 54999)
        upd("realme GT 7 Pro", "realme", 41999)
        upd("realme GT 6T", "realme", 35999)
        upd("realme GT 6", "realme", 37999)
        upd("realme 16 Pro Plus", "realme", 43999)
        upd("realme 16 Pro", "realme", 34999)
        upd("realme 14 Pro+", "realme", 29999)
        upd("realme 14 Pro", "realme", 24999)
        upd("realme 14x", "realme", 12999)
        upd("realme 14", "realme", 14999)
        upd("realme 13 Pro+", "realme", 25999)
        upd("realme 13 Pro", "realme", 18880)
        upd("realme 13 Plus", "realme", 17999)
        upd("realme 13x", "realme", 11999)
        upd("realme 13", "realme", 14999)
        upd("realme Narzo 70 Turbo", "realme", 15499)
        upd("realme Narzo 70 Pro", "realme", 18499)
        upd("realme Narzo 70", "realme", 13999)
        upd("realme Narzo 60 Pro", "realme", 18999)
        upd("realme Narzo 60", "realme", 15999)
        upd("realme C75", "realme", 12990)
        upd("realme C67", "realme", 11999)
        upd("realme C65", "realme", 10999)
        upd("realme C63", "realme", 9499)
        upd("realme C61", "realme", 8999)
        upd("realme C55", "realme", 10999)
        upd("realme C53", "realme", 9499)
        upd("realme C51", "realme", 7999)
        upd("realme C35", "realme", 8999)
        upd("realme C33", "realme", 7999)
        upd("Realme 13", "realme", 14999)
        upd("Realme C75", "realme", 12990)
        upd("Realme Narzo", "realme", 15499)
        cat_default("realme", 16999)

        # ── ABSOLUTE LAST RESORT — anything still unpriced ───────────────
        # Catches products with unknown/null categories
        db.execute(text("""
            UPDATE products
            SET price         = 357.0,
                compare_price = 464.1,
                is_priced     = TRUE,
                priced_at     = NOW()
            WHERE is_deleted = FALSE
              AND is_priced  = FALSE
        """))

        db.commit()

        # Count how many got priced this run
        still_left = db.execute(text(
            "SELECT COUNT(*) FROM products WHERE is_deleted=FALSE AND is_priced=FALSE"
        )).scalar()
        print(f"💰 Bulk pricing complete — {unpriced - still_left} products priced, {still_left} remaining")

    except Exception as e:
        print(f"⚠️  Bulk pricer error (non-fatal): {e}")
        try:
            db.rollback()
        except Exception:
            pass