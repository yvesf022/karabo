# app/routes/homepage_sections.py
"""
Smart Homepage Sections API
============================
Groups products by what they actually ARE — phones stay with phones,
jewellery stays with jewellery, chargers never mix with cosmetics.

Algorithm:
  1. Curated sections first: Flash Deals, New Arrivals, Best Sellers, Top Rated
  2. Smart taxonomy: scan every product's title + category + brand + description
     against a rich keyword dictionary to classify it into a named group
  3. Return sections sorted by product count — richer sections appear first

Endpoint: GET /api/homepage/sections
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload
# ✅ FIX 1: Added `func` — was missing, caused runtime crash on ORDER BY RANDOM()
from sqlalchemy import desc, func
from typing import Optional
import re
import time  # ✅ required for cache

from app.database import get_db
from app.models import Product

router = APIRouter(prefix="/homepage", tags=["homepage"])

SECTION_LIMIT    = 12
MIN_SECTION_SIZE = 3
MAX_CAT_SECTIONS = 12
CACHE_TTL        = 600  # cache homepage for 10 minutes

# ✅ module-level cache — resets on every server restart
_sections_cache: dict = {"data": None, "ts": 0.0}

# ═══════════════════════════════════════════════════════════════════════════
# KEYWORD TAXONOMY  —  (section_name, [keywords])
# More specific keywords come before generic ones.
# Longer multi-word phrases score higher when matched.
# ═══════════════════════════════════════════════════════════════════════════

TAXONOMY: list[tuple[str, list[str]]] = [
    ("Smartphones & Phones", [
        "smartphone","iphone","samsung galaxy","mobile phone","android phone",
        "cell phone","nokia","tecno","infinix","itel","redmi","oneplus","oppo","vivo","phone"
    ]),
    ("Tablets & iPads", ["tablet","ipad","android tablet","kindle","fire hd"]),
    ("Laptops & Computers", [
        "laptop","notebook","macbook","chromebook","desktop","pc computer","gaming laptop","ultrabook"
    ]),
    ("Headphones & Audio", [
        "headphone","earphone","earbuds","airpods","earpods","wireless earphone",
        "neckband","bluetooth speaker","soundbar","subwoofer","home theater","speaker"
    ]),
    ("Smartwatches", [
        "smartwatch","smart watch","fitness tracker","smart band","apple watch","galaxy watch","fit band"
    ]),
    ("Cameras & Photography", [
        "camera","dslr","mirrorless","action cam","gopro","lens","tripod","ring light","studio light"
    ]),
    ("Chargers & Cables", [
        "charger","charging cable","usb cable","type-c cable","lightning cable",
        "power bank","powerbank","fast charger","wireless charger","adapter plug","extension cord"
    ]),
    ("TVs & Displays", [
        "smart tv","led tv","oled","qled","television","monitor","display screen","projector","tv"
    ]),
    ("Gaming", [
        "playstation","ps4","ps5","xbox","nintendo","game controller","joystick","game console","gaming"
    ]),
    ("Skincare", [
        "serum","moisturizer","moisturiser","toner","cleanser","face wash","sunscreen","spf","retinol",
        "hyaluronic","vitamin c serum","face mask","eye cream","exfoliant","skin care","skincare",
        "face cream","anti aging","brightening","dark spot","niacinamide","aha bha","face oil"
    ]),
    ("Makeup & Cosmetics", [
        "lipstick","lip gloss","lip liner","mascara","eyeliner","eyeshadow","blush","bronzer",
        "highlighter","foundation","concealer","setting powder","primer","contour","makeup",
        "cosmetic","nail polish","nail art","makeup brush","beauty blender","false lash","eyebrow"
    ]),
    ("Perfume & Fragrance", [
        "perfume","cologne","fragrance","eau de parfum","eau de toilette",
        "body spray","deodorant","roll-on","antiperspirant","body mist","scent"
    ]),
    ("Hair Care", [
        "shampoo","conditioner","hair mask","hair oil","hair serum","hair treatment",
        "deep conditioner","leave-in","hair growth","wig","weave","hair extension","lace front",
        "closure","frontal","braiding hair","crochet hair","hair gel","edge control","hair spray"
    ]),
    ("Body Care", [
        "body butter","body scrub","body oil","body cream","shea butter","cocoa butter",
        "stretch mark","bath salt","bath bomb","shower gel","body wash","hand cream","foot cream"
    ]),
    ("Jewellery", [
        "necklace","bracelet","ring","earring","jewelry","jewellery","pendant","chain",
        "bangle","anklet","brooch","choker","locket","diamond ring","gold necklace","silver bracelet"
    ]),
    ("Watches", [
        "watch","timepiece","chronograph","rolex","casio","citizen","seiko","fossil",
        "analog watch","quartz watch"
    ]),
    ("Sunglasses & Eyewear", [
        "sunglasses","sunglass","eyewear","spectacle","glasses frame","reading glasses","polarized"
    ]),
    ("Women's Clothing", [
        "dress","ladies dress","bodycon","maxi dress","blouse","ladies top","women top",
        "skirt","jumpsuit","romper","ladies shirt","two-piece set","co-ord","crop top",
        "women jacket","ladies blazer"
    ]),
    ("Men's Clothing", [
        "men shirt","polo shirt","men trouser","chinos","men jeans","men suit","men jacket",
        "men blazer","men hoodie","men shorts","ankara","native wear","agbada"
    ]),
    ("Clothing", [
        "hoodie","sweatshirt","jogger","tracksuit","t-shirt","tshirt","jeans","denim",
        "shirt","pyjama","sleepwear","lingerie","underwear","bra","panties","boxers"
    ]),
    ("Women's Shoes", [
        "heels","stiletto","platform shoe","wedge shoe","women sneaker","ladies sneaker",
        "women boot","ankle boot","women sandal","flat shoe","ballet flat","women loafer","mule"
    ]),
    ("Men's Shoes", [
        "men sneaker","men shoe","men boot","oxford shoe","men loafer","derby shoe",
        "brogues","men sandal","men flip flop"
    ]),
    ("Shoes", ["sneaker","boot","sandal","shoe","slipper","flip flop","loafer"]),
    ("Bags & Purses", [
        "handbag","purse","tote bag","clutch","shoulder bag","crossbody","satchel",
        "women bag","ladies bag","backpack","rucksack","travel bag","duffel","wallet","card holder"
    ]),
    ("Fashion Accessories", [
        "belt","hat","cap","beanie","scarf","hijab","hair clip","hair pin","hair band",
        "headband","tie","bow tie","cufflink","glove","mittens"
    ]),
    ("Kitchen & Cooking", [
        "cookware","frying pan","blender","mixer","juicer","toaster","kettle",
        "rice cooker","air fryer","microwave","cutting board","kitchen","cooking",
        "bakeware","mug","plate","bowl","cutlery","pot","pan"
    ]),
    ("Home Decor", [
        "home decor","vase","candle","picture frame","wall art","mirror","lamp",
        "throw pillow","cushion","rug","carpet","curtain","tablecloth","plant pot","artificial flower"
    ]),
    ("Bedding & Bath", [
        "bedsheet","duvet","pillow case","towel","bath towel","comforter","blanket",
        "mattress","bed cover","quilt"
    ]),
    ("Fitness & Sports", [
        "dumbbell","barbell","resistance band","yoga mat","skipping rope","jump rope",
        "fitness","exercise","workout","protein","supplement","whey","creatine",
        "sports bottle","gym glove","sports bag","gym"
    ]),
    ("Health & Wellness", [
        "vitamin","herbal","wellness","massage","blood pressure","thermometer",
        "first aid","pain relief","essential oil","health"
    ]),
    ("Baby & Kids", [
        "baby","infant","toddler","kids","children","toy","doll","stroller","pram",
        "baby carrier","nappy","diaper","baby wipe","feeding bottle","pacifier"
    ]),
]


def _classify(product: Product) -> str:
    """Classify a product into a taxonomy section using keyword scoring."""
    haystack = " ".join(filter(None, [
        product.category or "",
        product.main_category or "",
        product.title or "",
        product.brand or "",
        product.short_description or "",
    ])).lower()
    haystack = re.sub(r"[^\w\s]", " ", haystack)

    best: Optional[str] = None
    top_score = 0

    for section_name, keywords in TAXONOMY:
        score = 0
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw.lower()) + r"\b", haystack):
                score += len(kw.split())
        if score > top_score:
            top_score = score
            best = section_name

    return best if top_score > 0 else "Other Products"


def _card(p: Product) -> dict:
    # Try primary image first, then any image, then None
    # Use denormalized main_image column first (fastest - no join needed)
    img = (getattr(p, 'main_image', None) or getattr(p, 'image_url', None)
           or next((i.image_url for i in p.images if i.is_primary), None)
           or (p.images[0].image_url if p.images else None))
    disc = None
    if p.compare_price and p.compare_price > p.price > 0:
        disc = round(((p.compare_price - p.price) / p.compare_price) * 100)
    return {
        "id": str(p.id),
        "title": p.title,
        "price": p.price,
        "compare_price": p.compare_price,
        "discount_pct": disc,
        "brand": p.brand,
        "category": p.category,
        "rating": p.rating,
        "rating_number": p.rating_number,
        "sales": p.sales,
        "in_stock": p.stock > 0,
        "main_image": img,
        "images": [i.image_url for i in p.images],
    }


def _active(db: Session):
    """Only return active, non-deleted products."""
    return db.query(Product).options(selectinload(Product.images)).filter(
        Product.status == "active",
        Product.is_deleted == False,
    )


@router.get("/sections")
def homepage_sections(db: Session = Depends(get_db)):
    global _sections_cache
    now = time.time()
    if _sections_cache["data"] is not None and (now - _sections_cache["ts"]) < CACHE_TTL:
        return _sections_cache["data"]

    from sqlalchemy import text as _text

    # ── Fast raw SQL card builder (no ORM image join needed) ──────────────────
    def _sql_card(r) -> dict:
        price, compare = r[2], r[3]
        disc = round(((compare - price) / compare) * 100) if compare and compare > price > 0 else None
        return {
            "id": str(r[0]), "title": r[1],
            "price": price, "compare_price": compare, "discount_pct": disc,
            "brand": r[4], "category": r[5],
            "rating": r[6], "rating_number": r[7],
            "sales": r[8], "in_stock": (r[9] or 0) > 0,
            "main_image": r[10], "images": [],
        }

    BASE_COLS = """
        id, title, price, compare_price, brand, category,
        rating, rating_number, sales, stock,
        COALESCE(main_image, image_url) AS img
    """
    BASE_WHERE = "status = 'active' AND is_deleted = FALSE"

    sections: list[dict] = []

    # 1 — Flash Deals
    flash_rows = db.execute(_text(f"""
        SELECT {BASE_COLS} FROM products
        WHERE {BASE_WHERE}
          AND compare_price IS NOT NULL
          AND compare_price > price
          AND stock > 0
        ORDER BY ((compare_price - price) / compare_price) DESC
        LIMIT :lim
    """), {"lim": SECTION_LIMIT}).fetchall()
    if flash_rows:
        sections.append({
            "key": "flash_deals", "title": "Flash Deals",
            "subtitle": "Biggest discounts right now",
            "badge": "SALE", "theme": "red",
            "view_all": "/store?sort=discount",
            "products": [_sql_card(r) for r in flash_rows],
        })

    # 2 — New Arrivals
    new_rows = db.execute(_text(f"""
        SELECT {BASE_COLS} FROM products
        WHERE {BASE_WHERE} AND stock > 0
        ORDER BY created_at DESC
        LIMIT :lim
    """), {"lim": SECTION_LIMIT}).fetchall()
    if new_rows:
        sections.append({
            "key": "new_arrivals", "title": "New Arrivals",
            "subtitle": "Fresh styles just landed",
            "badge": "NEW", "theme": "green",
            "view_all": "/store?sort=newest",
            "products": [_sql_card(r) for r in new_rows],
        })

    # 3 — Best Sellers
    best_rows = db.execute(_text(f"""
        SELECT {BASE_COLS} FROM products
        WHERE {BASE_WHERE} AND stock > 0
        ORDER BY sales DESC NULLS LAST, rating_number DESC NULLS LAST
        LIMIT :lim
    """), {"lim": SECTION_LIMIT}).fetchall()
    if best_rows:
        sections.append({
            "key": "best_sellers", "title": "Best Sellers",
            "subtitle": "What everyone is buying",
            "badge": None, "theme": "gold",
            "view_all": "/store?sort=popular",
            "products": [_sql_card(r) for r in best_rows],
        })

    # 4 — Top Rated
    rated_rows = db.execute(_text(f"""
        SELECT {BASE_COLS} FROM products
        WHERE {BASE_WHERE}
          AND rating >= 4.0
          AND rating_number >= 3
          AND stock > 0
        ORDER BY rating DESC NULLS LAST, rating_number DESC NULLS LAST
        LIMIT :lim
    """), {"lim": SECTION_LIMIT}).fetchall()
    if rated_rows:
        sections.append({
            "key": "top_rated", "title": "Top Rated",
            "subtitle": "Highest rated by customers",
            "badge": None, "theme": "gold",
            "view_all": "/store?sort=rating",
            "products": [_sql_card(r) for r in rated_rows],
        })

    # 5-N — Smart Category Sections
    # FAST: raw SQL fetches only the columns we need — no ORM image join.
    # The old approach used selectinload(Product.images) on 500 rows which
    # triggered thousands of SQL rows. This single query is ~10x faster.
    from sqlalchemy import text as _text
    rows = db.execute(_text("""
        SELECT id, title, price, compare_price, brand, category,
               main_category, short_description,
               COALESCE(main_image, image_url) AS img,
               rating, rating_number, sales, stock
        FROM products
        WHERE status = 'active'
          AND is_deleted = FALSE
          AND stock > 0
        ORDER BY RANDOM()
        LIMIT 500
    """)).fetchall()

    # Lightweight duck-typed object so _classify() works unchanged
    class _P:
        __slots__ = ("category", "main_category", "title", "brand", "short_description")
        def __init__(self, r):
            self.category          = r[5]
            self.main_category     = r[6]
            self.title             = r[1]
            self.brand             = r[4]
            self.short_description = r[7]

    def _fast_card(r) -> dict:
        price   = r[2]
        compare = r[3]
        disc    = None
        if compare and compare > price > 0:
            disc = round(((compare - price) / compare) * 100)
        return {
            "id": str(r[0]), "title": r[1],
            "price": price, "compare_price": compare, "discount_pct": disc,
            "brand": r[4], "category": r[5],
            "rating": r[9], "rating_number": r[10],
            "sales": r[11], "in_stock": (r[12] or 0) > 0,
            "main_image": r[8], "images": [],
        }

    buckets: dict[str, list] = {}
    for row in rows:
        name = _classify(_P(row))
        if name not in buckets:
            buckets[name] = []
        if len(buckets[name]) < SECTION_LIMIT:
            buckets[name].append(_fast_card(row))

    sorted_cats = sorted(
        [(n, prods) for n, prods in buckets.items() if len(prods) >= MIN_SECTION_SIZE],
        key=lambda x: len(x[1]),
        reverse=True,
    )[:MAX_CAT_SECTIONS]

    themes = ["forest", "navy", "plum", "teal", "rust", "slate", "olive", "rose", "indigo", "amber", "sage", "stone"]
    for i, (cat, prods) in enumerate(sorted_cats):
        # IMPORTANT: use ?q= (search) not ?category= (slug filter).
        # Taxonomy names like "Hair Care" never match DB category slugs like
        # "shampoo". Search finds products by keyword in title/description
        # so the View All link always shows real results.
        sections.append({
            "key":      f"cat_{i}",
            "title":    cat,
            "subtitle": f"Shop all {cat.lower()}",
            "badge":    None,
            "theme":    themes[i % len(themes)],
            "view_all": f"/store?q={cat}",
            "products": prods,
        })

    result = {"sections": sections, "total_sections": len(sections)}
    _sections_cache["data"] = result
    _sections_cache["ts"]   = time.time()
    return result