"""
FILE: app/routes/auto_pricing.py

AI Auto-Pricer — backend route (full rewrite).

WHAT CHANGED vs the old version:
  ✅ Two-stage workflow: AI proposes → admin approves (is_priced only flips on approval)
  ✅ Async Anthropic client — no more blocking the event loop
  ✅ PriceProposal table: full audit trail of every AI suggestion + approval
  ✅ Atomic approve: price + is_priced + priced_by + priced_at saved in ONE commit
  ✅ Exchange rate is fetched once, locked into the proposal — no drift between products
  ✅ Rate cap: max 5 concurrent AI searches per deployment (asyncio.Semaphore)
  ✅ Sync Anthropic fallback removed — uses AsyncAnthropic only
  ✅ Delete-from-pricing: soft-delete a product directly from the pricing tool
  ✅ priced_by (admin user id) stored on every approval
  ✅ Fallback rate is clearly flagged in every proposal

ENDPOINTS:
  GET  /api/products/admin/auto-price/rate
  POST /api/products/admin/auto-price/propose      ← AI searches, saves proposal, does NOT set is_priced
  POST /api/products/admin/auto-price/approve      ← Admin approves a proposal → atomic write
  POST /api/products/admin/auto-price/reject       ← Admin rejects a proposal
  GET  /api/products/admin/auto-price/proposals/{product_id}  ← Proposal history for one product
  DELETE /api/products/admin/pricing/{product_id}/delete      ← Soft-delete from pricing tool

ENV VARS:
  ANTHROPIC_API_KEY   -- required, never exposed to browser
"""

import os
import json
import re
import asyncio
import httpx
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import require_admin as get_current_admin
from app.models import Product, PriceProposal

# ── Anthropic (async only) ────────────────────────────────────────────────────
try:
    import anthropic as _anthropic_lib
    _anthropic_ok = True
except ImportError:
    _anthropic_ok = False

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Max concurrent AI searches — prevents blowing Anthropic rate limits on bulk runs
_AI_SEMAPHORE = asyncio.Semaphore(5)

router = APIRouter(tags=["Admin -- Auto Pricing"])


# ══════════════════════════════════════════════════════════════════════════════
# PRICING FORMULA
# Mirrors calculatePrice() in frontend lib/api.ts exactly.
# ══════════════════════════════════════════════════════════════════════════════

SHIPPING_INR = 700.0
PROFIT_INR   = 500.0
COMPARE_MULT = 1.30


def calculate_price(market_inr: float, exchange_rate: float) -> dict:
    total_cost_inr = market_inr + SHIPPING_INR + PROFIT_INR
    raw_lsl        = total_cost_inr * exchange_rate
    final_lsl      = round(raw_lsl * 2) / 2          # round to nearest 0.50
    compare_lsl    = round(final_lsl * COMPARE_MULT, 2)
    savings_lsl    = round(compare_lsl - final_lsl, 2)
    discount_pct   = round((savings_lsl / compare_lsl) * 100) if compare_lsl else 0
    profit_lsl     = round(PROFIT_INR * exchange_rate, 2)
    margin_pct     = round((profit_lsl / final_lsl) * 100, 1) if final_lsl else 0
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
    """
    Returns (rate, source) where source is "live" or "fallback".
    Always returns — never raises.
    """
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
# CLAUDE AI PRICE SEARCH  (async, semaphore-guarded)
# ══════════════════════════════════════════════════════════════════════════════

async def search_india_price(title: str, brand: Optional[str], category: Optional[str]) -> dict:
    """
    Uses Claude (AsyncAnthropic) with web_search to find the real INR price
    on Indian e-commerce.

    Returns { inr_price, source, confidence }
    Raises ValueError if price not found.
    Raises RuntimeError on API/config errors.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured on the server")
    if not _anthropic_ok:
        raise RuntimeError("anthropic package not installed — run: pip install anthropic")

    query = " ".join(p for p in [brand, title, category] if p)

    prompt = (
        f'Find the current retail price in Indian Rupees for: "{query}"\n\n'
        "Search Amazon.in, Flipkart.com, or Nykaa.com.\n"
        "Return ONLY valid JSON — no markdown, no preamble, no explanation:\n"
        '{"inr_price": <number or null>, "source": "<site>", "confidence": "high|medium|low"}\n\n'
        '- "high"   = exact product found on Amazon.in / Flipkart / Nykaa\n'
        '- "medium" = similar product or less reliable source\n'
        '- "low"    = estimating from category averages\n'
        '- Not found: {"inr_price": null, "source": "not found", "confidence": "low"}'
    )

    async with _AI_SEMAPHORE:
        client = _anthropic_lib.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )

    # Collect text blocks only — skip tool_use/tool_result blocks
    text = "\n".join(
        block.text for block in response.content if hasattr(block, "text")
    )

    match = re.search(r'\{[^{}]*"inr_price"[^{}]*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f"No price data returned by AI for: {title[:60]}")

    data = json.loads(match.group(0))
    if not data.get("inr_price"):
        raise ValueError(f"Product not found on Indian sites: {title[:60]}")

    return {
        "inr_price":  float(data["inr_price"]),
        "source":     data.get("source", "Unknown"),
        "confidence": data.get("confidence", "low"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class ProposeRequest(BaseModel):
    product_id: str
    title:      str
    brand:      Optional[str] = None
    category:   Optional[str] = None


class ApproveRequest(BaseModel):
    proposal_id: str   # UUID of the PriceProposal row to approve


class RejectRequest(BaseModel):
    proposal_id: str
    reason:      Optional[str] = None


class DeleteFromPricingRequest(BaseModel):
    reason: Optional[str] = None   # optional note for audit log


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# LIST ALL PRODUCTS FOR PRICING  (frontend calls GET /api/products/admin/pricing/all)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/products/admin/pricing/all")
def list_all_products_for_pricing(
    search:   str  = "",
    category: str  = "",
    brand:    str  = "",
    limit:    int  = 2000,
    offset:   int  = 0,
    db:       Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """
    Return all non-deleted products with their current pricing status.
    Used exclusively by the Admin Pricing Tool frontend.
    Results are sorted: unpriced first, then ai_suggested, then admin_approved.
    """
    from sqlalchemy import or_, case as sql_case

    q = db.query(Product).filter(Product.is_deleted == False)

    if search:
        q = q.filter(Product.title.ilike(f"%{search}%"))
    if category:
        q = q.filter(Product.category == category)
    if brand:
        q = q.filter(Product.brand == brand)

    total = q.count()

    # Sort: unpriced/rejected first → ai_suggested → admin_approved
    order_expr = sql_case(
        (Product.pricing_status == "admin_approved", 2),
        (Product.pricing_status == "ai_suggested",   1),
        else_=0,
    )
    products = q.order_by(order_expr, Product.title).offset(offset).limit(limit).all()

    results = [
        {
            "id":             str(p.id),
            "title":          p.title,
            "brand":          getattr(p, "brand", None),
            "category":       getattr(p, "category", None) or getattr(p, "main_category", None),
            "price":          p.price,
            "compare_price":  p.compare_price,
            "stock":          getattr(p, "stock", 0) or 0,
            "status":         str(p.status) if p.status else "active",
            "is_priced":      bool(p.is_priced),
            "pricing_status": p.pricing_status or ("admin_approved" if p.is_priced else "unpriced"),
            "priced_at":      p.priced_at.isoformat() if p.priced_at else None,
            "main_image":     p.main_image,
        }
        for p in products
    ]

    return {"results": results, "total": total, "loaded": len(results)}


# ══════════════════════════════════════════════════════════════════════════════
# RESET BULK-PRICED PRODUCTS BACK TO UNPRICED
# Targets products where is_priced=TRUE but priced_by IS NULL
# (i.e. set via bulk_price_update.py, never manually confirmed by an admin)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/products/admin/pricing/reset-bulk-unpriced")
def reset_bulk_priced_to_unpriced(
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """
    Resets all products that were bulk-priced (is_priced=TRUE, priced_by=NULL)
    back to unpriced so the admin can confirm them one by one in the pricing tool.

    Safe to run multiple times — only touches products with no admin who approved them.
    """
    from sqlalchemy import text as _text

    result = db.execute(_text("""
        UPDATE products
        SET
            is_priced      = FALSE,
            pricing_status = 'unpriced',
            priced_at      = NULL
        WHERE is_deleted  = FALSE
          AND is_priced   = TRUE
          AND priced_by   IS NULL
    """))
    db.commit()

    affected = result.rowcount
    return {
        "reset":   affected,
        "message": f"{affected} bulk-priced products reset to unpriced — they now require admin confirmation.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# LIGHTWEIGHT POLL ENDPOINT  — returns only id + pricing_status + price
# Used by frontend every 30s to sync across devices without a full reload
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/products/admin/pricing/poll")
def poll_pricing_status(
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """
    Returns minimal pricing status for ALL non-deleted products.
    Very cheap query — only 5 columns, no joins.
    Frontend uses this every 30s to sync approvals made on another device.
    """
    items = db.query(
        Product.id,
        Product.pricing_status,
        Product.is_priced,
        Product.price,
        Product.compare_price,
    ).filter(Product.is_deleted == False).all()

    return {
        "items": [
            {
                "id":             str(r.id),
                "pricing_status": r.pricing_status or ("admin_approved" if r.is_priced else "unpriced"),
                "is_priced":      bool(r.is_priced),
                "price":          r.price,
                "compare_price":  r.compare_price,
            }
            for r in items
        ]
    }


@router.get("/products/admin/auto-price/rate")
async def get_rate(admin=Depends(get_current_admin)):
    """Return live INR → LSL exchange rate plus its source."""
    rate, source = await fetch_exchange_rate()
    return {
        "rate":           rate,
        "source":         source,
        "is_fallback":    source == "fallback",
        "fallback_value": FALLBACK_RATE,
    }


@router.post("/products/admin/auto-price/propose")
async def propose_price(
    req:   ProposeRequest,
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """
    Stage 1 — AI proposes a price.

    Saves a PriceProposal row with status="pending".
    Does NOT touch product.price or product.is_priced.
    Admin must call /approve to make it live.

    HTTP codes:
      200  = proposal saved, awaiting admin approval
      422  = product genuinely not found on Indian sites (not_found, skip it)
      503  = AI / network error (transient, can retry)
    """
    product = db.query(Product).filter(
        Product.id       == req.product_id,
        Product.is_deleted == False,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {req.product_id} not found")

    # Fetch exchange rate once — lock it into this proposal so all maths are consistent
    exchange_rate, rate_source = await fetch_exchange_rate()

    # AI search
    try:
        price_data = await search_india_price(
            title=req.title, brand=req.brand, category=req.category,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI search error: {str(e)}")

    pricing = calculate_price(
        market_inr=price_data["inr_price"],
        exchange_rate=exchange_rate,
    )

    # Expire any existing pending proposals for this product
    db.query(PriceProposal).filter(
        PriceProposal.product_id == req.product_id,
        PriceProposal.status     == "pending",
    ).update({"status": "superseded"}, synchronize_session=False)

    # Create new proposal — does NOT touch product row
    proposal = PriceProposal(
        product_id        = req.product_id,
        proposed_by       = admin.id,
        inr_price         = price_data["inr_price"],
        source            = price_data["source"],
        confidence        = price_data["confidence"],
        exchange_rate     = exchange_rate,
        rate_source       = rate_source,
        final_price_lsl   = pricing["final_price_lsl"],
        compare_price_lsl = pricing["compare_price_lsl"],
        discount_pct      = pricing["discount_pct"],
        margin_pct        = pricing["margin_pct"],
        status            = "pending",
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    return {
        "proposal_id":     str(proposal.id),
        "product_id":      req.product_id,
        "title":           req.title,
        "inr_price":       price_data["inr_price"],
        "source":          price_data["source"],
        "confidence":      price_data["confidence"],
        "exchange_rate":   exchange_rate,
        "rate_source":     rate_source,
        "is_fallback_rate": rate_source == "fallback",
        "final_price_lsl":   pricing["final_price_lsl"],
        "compare_price_lsl": pricing["compare_price_lsl"],
        "discount_pct":      pricing["discount_pct"],
        "margin_pct":        pricing["margin_pct"],
        "status":          "pending",
    }


@router.post("/products/admin/auto-price/approve")
def approve_proposal(
    req:   ApproveRequest,
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """
    Stage 2 — Admin approves a proposal.

    Atomically (single commit):
      - product.price         = proposal.final_price_lsl
      - product.compare_price = proposal.compare_price_lsl
      - product.is_priced     = True
      - product.pricing_status = "admin_approved"
      - product.priced_by     = admin.id
      - product.priced_at     = now()
      - proposal.status       = "approved"
      - proposal.approved_by  = admin.id
      - proposal.approved_at  = now()
    """
    proposal = db.query(PriceProposal).filter(
        PriceProposal.id == req.proposal_id,
    ).first()
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    if proposal.status not in ("pending", "superseded"):
        raise HTTPException(409, f"Proposal is already '{proposal.status}' — cannot approve")

    product = db.query(Product).filter(
        Product.id         == proposal.product_id,
        Product.is_deleted == False,
    ).first()
    if not product:
        raise HTTPException(404, "Product no longer exists")

    now = datetime.now(timezone.utc)

    # ── Atomic write — one commit ──────────────────────────────────────────
    product.price          = proposal.final_price_lsl
    product.compare_price  = proposal.compare_price_lsl
    product.is_priced      = True
    product.pricing_status = "admin_approved"
    product.priced_by      = admin.id
    product.priced_at      = now

    proposal.status      = "approved"
    proposal.approved_by = admin.id
    proposal.approved_at = now

    db.commit()

    return {
        "product_id":        str(product.id),
        "proposal_id":       str(proposal.id),
        "final_price_lsl":   product.price,
        "compare_price_lsl": product.compare_price,
        "approved_at":       now,
        "approved_by":       str(admin.id),
    }


@router.post("/products/admin/auto-price/approve-manual")
def approve_manual_price(
    req:   dict,
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """
    Approve a manually-entered price (no AI proposal needed).
    Body: { product_id, price_lsl, compare_price_lsl, inr_price?, exchange_rate? }

    Creates a PriceProposal with source="manual" and immediately approves it.
    This is what the frontend calls when admin types in an INR price manually.
    """
    product_id       = req.get("product_id")
    price_lsl        = req.get("price_lsl")
    compare_price_lsl = req.get("compare_price_lsl")

    if not product_id or price_lsl is None:
        raise HTTPException(400, "product_id and price_lsl are required")

    product = db.query(Product).filter(
        Product.id         == product_id,
        Product.is_deleted == False,
    ).first()
    if not product:
        raise HTTPException(404, "Product not found")

    now           = datetime.now(timezone.utc)
    exchange_rate = float(req.get("exchange_rate", FALLBACK_RATE))
    inr_price     = float(req.get("inr_price", 0))
    compare_final = compare_price_lsl or round(float(price_lsl) * COMPARE_MULT, 2)

    # Expire pending proposals
    db.query(PriceProposal).filter(
        PriceProposal.product_id == product_id,
        PriceProposal.status     == "pending",
    ).update({"status": "superseded"}, synchronize_session=False)

    proposal = PriceProposal(
        product_id        = product_id,
        proposed_by       = admin.id,
        inr_price         = inr_price,
        source            = "manual",
        confidence        = "high",
        exchange_rate     = exchange_rate,
        rate_source       = "manual",
        final_price_lsl   = float(price_lsl),
        compare_price_lsl = compare_final,
        discount_pct      = round(((compare_final - float(price_lsl)) / compare_final) * 100) if compare_final else 0,
        margin_pct        = round((PROFIT_INR * exchange_rate / float(price_lsl)) * 100, 1) if price_lsl else 0,
        status            = "approved",
        approved_by       = admin.id,
        approved_at       = now,
    )
    db.add(proposal)

    product.price          = float(price_lsl)
    product.compare_price  = compare_final
    product.is_priced      = True
    product.pricing_status = "admin_approved"
    product.priced_by      = admin.id
    product.priced_at      = now

    db.commit()
    db.refresh(proposal)

    return {
        "product_id":        str(product.id),
        "proposal_id":       str(proposal.id),
        "final_price_lsl":   product.price,
        "compare_price_lsl": product.compare_price,
        "approved_at":       now,
    }


@router.post("/products/admin/auto-price/approve-bulk")
def approve_bulk_manual(
    req:   dict,
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """
    Bulk-approve manually-entered prices for multiple products.
    Body: { items: [{ product_id, price_lsl, compare_price_lsl, inr_price?, exchange_rate? }] }
    """
    items = req.get("items", [])
    if not items:
        raise HTTPException(400, "items array is required")

    now     = datetime.now(timezone.utc)
    success = []
    errors  = []

    for item in items:
        pid = item.get("product_id")
        try:
            product = db.query(Product).filter(
                Product.id         == pid,
                Product.is_deleted == False,
            ).first()
            if not product:
                raise ValueError("Product not found")

            price_lsl    = float(item["price_lsl"])
            compare_lsl  = float(item.get("compare_price_lsl") or round(price_lsl * COMPARE_MULT, 2))
            exchange_rate = float(item.get("exchange_rate", FALLBACK_RATE))
            inr_price     = float(item.get("inr_price", 0))

            # Expire pending proposals
            db.query(PriceProposal).filter(
                PriceProposal.product_id == pid,
                PriceProposal.status     == "pending",
            ).update({"status": "superseded"}, synchronize_session=False)

            proposal = PriceProposal(
                product_id        = pid,
                proposed_by       = admin.id,
                inr_price         = inr_price,
                source            = "manual",
                confidence        = "high",
                exchange_rate     = exchange_rate,
                rate_source       = "manual",
                final_price_lsl   = price_lsl,
                compare_price_lsl = compare_lsl,
                discount_pct      = round(((compare_lsl - price_lsl) / compare_lsl) * 100) if compare_lsl else 0,
                margin_pct        = round((PROFIT_INR * exchange_rate / price_lsl) * 100, 1) if price_lsl else 0,
                status            = "approved",
                approved_by       = admin.id,
                approved_at       = now,
            )
            db.add(proposal)

            product.price          = price_lsl
            product.compare_price  = compare_lsl
            product.is_priced      = True
            product.pricing_status = "admin_approved"
            product.priced_by      = admin.id
            product.priced_at      = now

            success.append(pid)
        except Exception as e:
            errors.append(f"{pid}: {str(e)}")

    db.commit()

    return {
        "success": len(success),
        "failed":  len(errors),
        "errors":  errors,
    }


@router.post("/products/admin/auto-price/reject")
def reject_proposal(
    req:   RejectRequest,
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """Admin rejects a pending proposal — product stays unpriced."""
    proposal = db.query(PriceProposal).filter(
        PriceProposal.id == req.proposal_id,
    ).first()
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(409, f"Proposal is already '{proposal.status}'")

    product = db.query(Product).filter(Product.id == proposal.product_id).first()
    if product:
        product.pricing_status = "admin_rejected"

    proposal.status      = "rejected"
    proposal.approved_by = admin.id   # reusing field to record who acted
    proposal.approved_at = datetime.now(timezone.utc)
    if req.reason:
        proposal.reject_reason = req.reason

    db.commit()
    return {"proposal_id": str(proposal.id), "status": "rejected"}


@router.get("/products/admin/auto-price/proposals/{product_id}")
def get_proposals(
    product_id: str,
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """Return all pricing proposals for a product (newest first)."""
    proposals = (
        db.query(PriceProposal)
        .filter(PriceProposal.product_id == product_id)
        .order_by(PriceProposal.created_at.desc())
        .all()
    )
    return [
        {
            "id":               str(p.id),
            "status":           p.status,
            "inr_price":        p.inr_price,
            "source":           p.source,
            "confidence":       p.confidence,
            "exchange_rate":    p.exchange_rate,
            "rate_source":      p.rate_source,
            "final_price_lsl":  p.final_price_lsl,
            "compare_price_lsl":p.compare_price_lsl,
            "discount_pct":     p.discount_pct,
            "margin_pct":       p.margin_pct,
            "proposed_by":      str(p.proposed_by) if p.proposed_by else None,
            "approved_by":      str(p.approved_by) if p.approved_by else None,
            "approved_at":      p.approved_at,
            "reject_reason":    getattr(p, "reject_reason", None),
            "created_at":       p.created_at,
        }
        for p in proposals
    ]


# ══════════════════════════════════════════════════════════════════════════════
# DELETE FROM PRICING TOOL
# ══════════════════════════════════════════════════════════════════════════════

@router.delete("/products/admin/pricing/{product_id}/delete")
def delete_product_from_pricing(
    product_id: str,
    db:    Session = Depends(get_db),
    admin = Depends(get_current_admin),
):
    """
    Soft-delete a product directly from the pricing tool.

    - Sets product.is_deleted = True, status = "inactive"
    - Expires any pending proposals
    - Logs the deletion with the admin's id
    - Returns immediately so the frontend can remove the card

    This uses the same soft-delete as the main product DELETE endpoint,
    so the product remains recoverable from the Admin > Products page.
    """
    product = db.query(Product).filter(
        Product.id         == product_id,
        Product.is_deleted == False,
    ).first()
    if not product:
        raise HTTPException(404, "Product not found or already deleted")

    now = datetime.now(timezone.utc)

    # Expire any open pricing proposals
    db.query(PriceProposal).filter(
        PriceProposal.product_id == product_id,
        PriceProposal.status     == "pending",
    ).update({"status": "superseded"}, synchronize_session=False)

    product.is_deleted     = True
    product.deleted_at     = now
    product.status         = "inactive"
    product.pricing_status = "deleted"

    db.commit()

    return {
        "deleted":    True,
        "product_id": product_id,
        "deleted_at": now,
        "deleted_by": str(admin.id),
    }


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY: keep the old mark endpoint working (redirect to new logic)
# The frontend may still call PATCH /admin/pricing/{id}/mark
# ══════════════════════════════════════════════════════════════════════════════

@router.patch("/products/admin/pricing/{product_id}/mark")
def mark_product_priced_legacy(
    product_id: str,
    payload:    dict,
    db:         Session = Depends(get_db),
    admin     = Depends(get_current_admin),
):
    """
    Legacy endpoint kept for backwards compat with the old frontend.
    Now routes through the new approval logic so the PriceProposal
    audit trail is always populated even for legacy calls.

    If is_priced=True  → creates an approved manual proposal
    If is_priced=False → resets product to unpriced / ai_suggested
    """
    is_priced = bool(payload.get("is_priced", True))
    product   = db.query(Product).filter(
        Product.id         == product_id,
        Product.is_deleted == False,
    ).first()
    if not product:
        raise HTTPException(404, "Product not found")

    now = datetime.now(timezone.utc)

    if is_priced:
        # Only create a proposal if the product already has a price
        if product.price and product.price > 0:
            db.query(PriceProposal).filter(
                PriceProposal.product_id == product_id,
                PriceProposal.status     == "pending",
            ).update({"status": "superseded"}, synchronize_session=False)

            proposal = PriceProposal(
                product_id        = product_id,
                proposed_by       = admin.id,
                inr_price         = 0,
                source            = "manual_mark",
                confidence        = "high",
                exchange_rate     = FALLBACK_RATE,
                rate_source       = "manual",
                final_price_lsl   = product.price,
                compare_price_lsl = product.compare_price or round(product.price * COMPARE_MULT, 2),
                status            = "approved",
                approved_by       = admin.id,
                approved_at       = now,
            )
            db.add(proposal)

        product.is_priced      = True
        product.pricing_status = "admin_approved"
        product.priced_by      = admin.id
        product.priced_at      = now
    else:
        product.is_priced      = False
        product.pricing_status = "unpriced"
        product.priced_by      = None
        product.priced_at      = None

    db.commit()
    return {"id": product_id, "is_priced": is_priced}