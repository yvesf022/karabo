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
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
import re

from app.database import get_db
from app.models import Product

router = APIRouter(prefix="/homepage", tags=["homepage"])

SECTION_LIMIT   = 16
MIN_SECTION_SIZE = 3
MAX_CAT_SECTIONS = 12

# ═══════════════════════════════════════════════════════════════════════════
# KEYWORD TAXONOMY  —  (section_name, [keywords])
# More specific keywords come before generic ones.
# Longer multi-word phrases score higher when matched.
# ═══════════════════════════════════════════════════════════════════════════

TAXONOMY: list[tuple[str, list[str]]] = [
    # Phones & Tablets
    ("Smartphones & Phones", [
        "smartphone","iphone","samsung galaxy","mobile phone","android phone",
        "cell phone","nokia","tecno","infinix","itel","redmi","oneplus","oppo","vivo","phone"
    ]),
    ("Tablets & iPads", ["tablet","ipad","android tablet","kindle","fire hd"]),
    # Computers
    ("Laptops & Computers", [
        "laptop","notebook","macbook","chromebook","desktop","pc computer","gaming laptop","ultrabook"
    ]),
    # Audio
    ("Headphones & Audio", [
        "headphone","earphone","earbuds","airpods","earpods","wireless earphone",
        "neckband","bluetooth speaker","soundbar","subwoofer","home theater","speaker"
    ]),
    # Wearables
    ("Smartwatches", [
        "smartwatch","smart watch","fitness tracker","smart band","apple watch","galaxy watch","fit band"
    ]),
    # Cameras
    ("Cameras & Photography", [
        "camera","dslr","mirrorless","action cam","gopro","lens","tripod","ring light","studio light"
    ]),
    # Chargers — must come AFTER phones so "phone charger" doesn't hit phones section
    ("Chargers & Cables", [
        "charger","charging cable","usb cable","type-c cable","lightning cable",
        "power bank","powerbank","fast charger","wireless charger","adapter plug","extension cord"
    ]),
    # TV
    ("TVs & Displays", [
        "smart tv","led tv","oled","qled","television","monitor","display screen","projector","tv"
    ]),
    # Gaming
    ("Gaming", [
        "playstation","ps4","ps5","xbox","nintendo","game controller","joystick","game console","gaming"
    ]),

    # ── Beauty ──────────────────────────────────────────────────
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

    # ── Jewellery & Accessories ─────────────────────────────────
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

    # ── Fashion ────────────────────────────────────────────────
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

    # ── Home ──────────────────────────────────────────────────
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

    # ── Health & Fitness ──────────────────────────────────────
    ("Fitness & Sports", [
        "dumbbell","barbell","resistance band","yoga mat","skipping rope","jump rope",
        "fitness","exercise","workout","protein","supplement","whey","creatine",
        "sports bottle","gym glove","sports bag","gym"
    ]),
    ("Health & Wellness", [
        "vitamin","herbal","wellness","massage","blood pressure","thermometer",
        "first aid","pain relief","essential oil","health"
    ]),

    # ── Baby & Kids ───────────────────────────────────────────
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
                score += len(kw.split())  # multi-word kw = higher specificity
        if score > top_score:
            top_score = score
            best = section_name

    return best if top_score > 0 else "Other Products"


def _card(p: Product) -> dict:
    img = next((i.image_url for i in p.images if i.is_primary), None) or \
          (p.images[0].image_url if p.images else None)
    disc = None
    if p.compare_price and p.compare_price > p.price > 0:
        disc = round(((p.compare_price - p.price) / p.compare_price) * 100)
    return {
        "id": str(p.id), "title": p.title,
        "price": p.price, "compare_price": p.compare_price,
        "discount_pct": disc, "brand": p.brand, "category": p.category,
        "rating": p.rating, "rating_number": p.rating_number,
        "sales": p.sales, "in_stock": p.stock > 0, "main_image": img,
    }


def _active(db: Session):
    return db.query(Product).filter(
        Product.status == "active",
        Product.is_deleted == False,
    )


@router.get("/sections")
def homepage_sections(db: Session = Depends(get_db)):
    sections: list[dict] = []

    # 1 — Flash Deals
    flash = (_active(db)
        .filter(Product.compare_price != None, Product.compare_price > Product.price, Product.stock > 0)
        .order_by(desc((Product.compare_price - Product.price) / Product.compare_price))
        .limit(SECTION_LIMIT).all())
    if flash:
        sections.append({"key":"flash_deals","title":"Flash Deals","subtitle":"Biggest discounts right now",
            "badge":"SALE","theme":"red","view_all":"/store?sort=discount","products":[_card(p) for p in flash]})

    # 2 — New Arrivals
    new = (_active(db).filter(Product.stock > 0).order_by(Product.created_at.desc()).limit(SECTION_LIMIT).all())
    if new:
        sections.append({"key":"new_arrivals","title":"New Arrivals","subtitle":"Fresh styles just landed",
            "badge":"NEW","theme":"green","view_all":"/store?sort=newest","products":[_card(p) for p in new]})

    # 3 — Best Sellers
    best = (_active(db).filter(Product.sales > 0, Product.stock > 0).order_by(Product.sales.desc()).limit(SECTION_LIMIT).all())
    if best:
        sections.append({"key":"best_sellers","title":"Best Sellers","subtitle":"What everyone is buying",
            "badge":None,"theme":"gold","view_all":"/store?sort=popular","products":[_card(p) for p in best]})

    # 4 — Top Rated
    rated = (_active(db).filter(Product.rating >= 4.0, Product.rating_number >= 3, Product.stock > 0)
        .order_by(Product.rating.desc(), Product.rating_number.desc()).limit(SECTION_LIMIT).all())
    if rated:
        sections.append({"key":"top_rated","title":"Top Rated","subtitle":"Highest rated by customers",
            "badge":None,"theme":"gold","view_all":"/store?sort=rating","products":[_card(p) for p in rated]})

    # 5-N — Smart Category Sections
    all_products = (_active(db).filter(Product.stock > 0)
        .order_by(Product.rating.desc(), Product.sales.desc()).all())

    buckets: dict[str, list] = {}
    for p in all_products:
        name = _classify(p)
        if name not in buckets:
            buckets[name] = []
        if len(buckets[name]) < SECTION_LIMIT:
            buckets[name].append(_card(p))

    sorted_cats = sorted(
        [(n, prods) for n, prods in buckets.items() if len(prods) >= MIN_SECTION_SIZE],
        key=lambda x: len(x[1]), reverse=True
    )[:MAX_CAT_SECTIONS]

    themes = ["forest","navy","plum","teal","rust","slate","olive","rose","indigo","amber","sage","stone"]
    for i, (cat, prods) in enumerate(sorted_cats):
        slug = cat.lower().replace(" & "," ").replace(" ","_").replace("&","and")
        sections.append({
            "key": f"cat_{slug}", "title": cat,
            "subtitle": f"Shop all {cat.lower()}",
            "badge": None, "theme": themes[i % len(themes)],
            "view_all": f"/store?q={cat.split()[0]}",
            "products": prods,
        })

    return {"sections": sections, "total_sections": len(sections)}