"""
FILE: app/routes/auto_pricing.py

AI Auto-Pricer — backend route.

Endpoints:
  GET  /api/products/admin/auto-price/rate
       Returns current INR -> LSL exchange rate.

  POST /api/products/admin/auto-price/search
       Body: { product_id, title, brand, category }
       1. Searches Google India via Claude AI (web_search tool) for the INR price
       2. Calculates Maloti price using same formula as frontend calculatePrice()
       3. Saves price to DB immediately (product.price + product.compare_price)
       4. Marks product.is_priced = True, product.priced_at = now()
       5. Returns the full result

SETUP:
  pip install anthropic httpx

ENV VARS:
  ANTHROPIC_API_KEY   -- required, never exposed to browser
"""

import os
import json
import re
import httpx
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.admin_auth import get_current_admin
from app.models import Product

# ── Anthropic ─────────────────────────────────────────────────────────────────
try:
    import anthropic as _anthropic_lib
    _anthropic_ok = True
except ImportError:
    _anthropic_ok = False

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

router = APIRouter(tags=["Admin -- Auto Pricing"])


# ══════════════════════════════════════════════════════════════════════════════
# PRICING FORMULA
# Mirrors calculatePrice() in frontend lib/api.ts exactly.
# ══════════════════════════════════════════════════════════════════════════════

SHIPPING_INR = 700.0
PROFIT_INR   = 500.0
COMPARE_MULT = 1.30


def calculate_price(market_inr: float, exchange_rate: float) -> dict:
    total_cost_inr    = market_inr + SHIPPING_INR + PROFIT_INR
    raw_lsl           = total_cost_inr * exchange_rate
    final_lsl         = round(raw_lsl * 2) / 2          # round to nearest 0.50
    compare_lsl       = round(final_lsl * COMPARE_MULT, 2)
    savings_lsl       = round(compare_lsl - final_lsl, 2)
    discount_pct      = round((savings_lsl / compare_lsl) * 100) if compare_lsl else 0
    profit_lsl        = round(PROFIT_INR * exchange_rate, 2)
    margin_pct        = round((profit_lsl / final_lsl) * 100, 1) if final_lsl else 0
    return {
        "market_inr":        market_inr,
        "shipping_inr":      SHIPPING_INR,
        "profit_inr":        PROFIT_INR,
        "total_cost_inr":    round(total_cost_inr, 2),
        "exchange_rate":     exchange_rate,
        "final_price_lsl":   round(final_lsl, 2),
        "compare_price_lsl": compare_lsl,
        "savings_lsl":       savings_lsl,
        "discount_pct":      discount_pct,
        "margin_pct":        margin_pct,
    }


# ══════════════════════════════════════════════════════════════════════════════
# EXCHANGE RATE
# ══════════════════════════════════════════════════════════════════════════════

FALLBACK_RATE = 0.21


async def fetch_exchange_rate() -> tuple[float, str]:
    for url in [
        "https://api.exchangerate-api.com/v4/latest/INR",
        "https://open.er-api.com/v6/latest/INR",
    ]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    rate = r.json().get("rates", {}).get("LSL")
                    if rate and float(rate) > 0:
                        return float(rate), "live"
        except Exception:
            continue
    return FALLBACK_RATE, "fallback"


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE AI PRICE SEARCH
# ══════════════════════════════════════════════════════════════════════════════

async def search_india_price(title: str, brand: str | None, category: str | None) -> dict:
    """
    Uses Claude with web_search to find the real INR price on Indian e-commerce.
    Returns { inr_price, source, confidence }
    Raises ValueError if price not found or API unavailable.
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set in server environment variables")
    if not _anthropic_ok:
        raise ValueError("anthropic package not installed -- run: pip install anthropic")

    query = " ".join(p for p in [brand, title, category] if p)

    prompt = (
        f'Find the current retail price in Indian Rupees for: "{query}"\n\n'
        "Search Amazon.in, Flipkart.com, or Nykaa.com.\n"
        'Return ONLY this JSON, no other text:\n'
        '{"inr_price": <number or null>, "source": "<site>", "confidence": "high|medium|low"}\n\n'
        '- "high" = exact product found on Amazon.in / Flipkart / Nykaa\n'
        '- "medium" = similar product or less reliable source\n'
        '- "low" = estimating from category\n'
        '- Not found: {"inr_price": null, "source": "not found", "confidence": "low"}'
    )

    client = _anthropic_lib.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )

    # Collect text blocks only (skip tool_use blocks)
    text = "\n".join(
        block.text for block in response.content if hasattr(block, "text")
    )

    match = re.search(r'\{[^{}]*"inr_price"[^{}]*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f"No price data returned for: {title[:60]}")

    data = json.loads(match.group(0))
    if not data.get("inr_price"):
        raise ValueError(f"Not found on Indian sites: {title[:60]}")

    return {
        "inr_price":  float(data["inr_price"]),
        "source":     data.get("source", "Unknown"),
        "confidence": data.get("confidence", "low"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class AutoPriceRequest(BaseModel):
    product_id: str
    title:      str
    brand:      str | None = None
    category:   str | None = None


class AutoPriceResponse(BaseModel):
    product_id:        str
    title:             str
    inr_price:         float
    source:            str
    confidence:        str
    exchange_rate:     float
    final_price_lsl:   float
    compare_price_lsl: float
    discount_pct:      int
    margin_pct:        float
    saved:             bool
    error:             str | None = None


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/products/admin/auto-price/rate")
async def get_rate(admin=Depends(get_current_admin)):
    """Return live INR -> LSL exchange rate."""
    rate, source = await fetch_exchange_rate()
    return {"rate": rate, "source": source}


@router.post("/products/admin/auto-price/search", response_model=AutoPriceResponse)
async def auto_price_product(
    req:   AutoPriceRequest,
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """
    Find price on Google India, calculate Maloti price, save to DB, return result.
    - 422 = product not found on Indian sites (frontend marks as not_found, moves on)
    - 503 = AI/network error (frontend auto-retries)
    - 200 + saved=false = found but DB write failed (frontend flags it)
    - 200 + saved=true  = fully done
    """

    # 1. Verify product exists in DB
    product = db.query(Product).filter(
        Product.id == req.product_id,
        Product.is_deleted == False,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {req.product_id} not found")

    # 2. Get live exchange rate
    exchange_rate, _ = await fetch_exchange_rate()

    # 3. Claude AI searches Google India for the INR price
    try:
        price_data = await search_india_price(
            title=req.title, brand=req.brand, category=req.category,
        )
    except ValueError as e:
        # Price genuinely not found -- frontend should mark not_found, not retry
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # Network/API error -- frontend should retry
        raise HTTPException(status_code=503, detail=f"AI search error: {str(e)}")

    # 4. Calculate Maloti price
    pricing = calculate_price(
        market_inr=price_data["inr_price"],
        exchange_rate=exchange_rate,
    )

    # 5. Save to DB immediately
    try:
        product.price         = pricing["final_price_lsl"]
        product.compare_price = pricing["compare_price_lsl"]
        product.is_priced     = True
        product.priced_at     = datetime.now(timezone.utc)
        db.commit()
        db.refresh(product)
        saved = True
        save_error = None
    except Exception as e:
        db.rollback()
        saved = False
        save_error = f"DB save failed: {str(e)}"

    return AutoPriceResponse(
        product_id        = req.product_id,
        title             = req.title,
        inr_price         = price_data["inr_price"],
        source            = price_data["source"],
        confidence        = price_data["confidence"],
        exchange_rate     = exchange_rate,
        final_price_lsl   = pricing["final_price_lsl"],
        compare_price_lsl = pricing["compare_price_lsl"],
        discount_pct      = pricing["discount_pct"],
        margin_pct        = pricing["margin_pct"],
        saved             = saved,
        error             = save_error,
    )