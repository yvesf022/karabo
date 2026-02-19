from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from typing import Optional
from datetime import datetime, timezone, timedelta
import re

from app.database import get_db
from app.dependencies import require_admin
from app.models import (
    Product, ProductImage, ProductVariant, ProductStatus,
    Order, OrderStatus, ShippingStatus,
    Payment, PaymentStatus, PaymentProof, PaymentStatusHistory,
    User, AuditLog, InventoryAdjustment,
    Store, BulkUpload,
    Cart, CartItem, Wishlist, Review, Notification,
    OrderItem, OrderReturn, OrderTracking, OrderNote,
    Coupon, CouponUsage, Wallet, WalletTransaction,
    RecentlyViewed,
)
from app.passwords import verify_password

router = APIRouter(prefix="/admin", tags=["admin"])


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _log(db, admin, action, entity_type, entity_id, before=None, after=None, meta=None):
    db.add(AuditLog(
        admin_id=admin.id if admin else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=before,
        after=after,
        meta=meta,
    ))


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@router.get("/dashboard")
def admin_dashboard(db: Session = Depends(get_db), admin=Depends(require_admin)):
    total_products    = db.query(Product).filter(Product.is_deleted == False).count()
    active_products   = db.query(Product).filter(Product.status == "active", Product.is_deleted == False).count()
    total_orders      = db.query(Order).filter(Order.is_deleted == False).count()
    paid_orders       = db.query(Order).filter(Order.status == OrderStatus.paid, Order.is_deleted == False).count()
    pending_orders    = db.query(Order).filter(Order.status == OrderStatus.pending, Order.is_deleted == False).count()
    total_revenue     = db.query(func.sum(Order.total_amount)).filter(Order.status == OrderStatus.paid, Order.is_deleted == False).scalar() or 0
    low_stock         = db.query(Product).filter(Product.stock > 0, Product.stock <= Product.low_stock_threshold, Product.is_deleted == False).count()
    out_of_stock      = db.query(Product).filter(Product.stock == 0, Product.is_deleted == False).count()
    total_users       = db.query(User).filter(User.role == "user").count()
    pending_payments  = db.query(Payment).filter(Payment.status.in_([PaymentStatus.pending, PaymentStatus.on_hold])).count()

    return {
        "total_products":    total_products,
        "active_products":   active_products,
        "total_orders":      total_orders,
        "paid_orders":       paid_orders,
        "pending_orders":    pending_orders,
        "total_revenue":     round(total_revenue, 2),
        "low_stock_count":   low_stock,
        "out_of_stock_count": out_of_stock,
        "total_users":       total_users,
        "pending_payments":  pending_payments,
    }


# ─────────────────────────────────────────────
# ANALYTICS ENGINE
# ─────────────────────────────────────────────

@router.get("/analytics/overview")
def analytics_overview(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    days: int = Query(30, ge=1, le=365),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    revenue      = db.query(func.sum(Order.total_amount)).filter(Order.status == OrderStatus.paid, Order.created_at >= since).scalar() or 0
    orders_count = db.query(Order).filter(Order.created_at >= since, Order.is_deleted == False).count()
    paid_count   = db.query(Order).filter(Order.status == OrderStatus.paid, Order.created_at >= since).count()
    new_products = db.query(Product).filter(Product.created_at >= since, Product.is_deleted == False).count()
    new_users    = db.query(User).filter(User.created_at >= since, User.role == "user").count()
    return {
        "period_days":     days,
        "revenue":         round(revenue, 2),
        "orders":          orders_count,
        "paid_orders":     paid_count,
        "conversion_rate": round((paid_count / orders_count * 100) if orders_count else 0, 2),
        "new_products":    new_products,
        "new_users":       new_users,
    }


@router.get("/analytics/revenue")
def analytics_revenue(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    days: int = Query(30, ge=1, le=365),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        text("""
            SELECT DATE(created_at) as day, SUM(total_amount) as revenue, COUNT(*) as orders
            FROM orders
            WHERE status = 'paid' AND created_at >= :since AND is_deleted = FALSE
            GROUP BY DATE(created_at)
            ORDER BY day ASC
        """),
        {"since": since}
    ).fetchall()
    total = sum(r.revenue for r in rows)
    return {
        "total_revenue": round(total, 2),
        "period_days":   days,
        "daily": [
            {"date": str(r.day), "revenue": round(r.revenue, 2), "orders": r.orders}
            for r in rows
        ],
    }


@router.get("/analytics/top-products")
def analytics_top_products(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    limit: int = Query(10, ge=1, le=50),
):
    products = db.query(Product).filter(Product.is_deleted == False).order_by(Product.sales.desc()).limit(limit).all()
    return [
        {
            "id":      str(p.id),
            "title":   p.title,
            "sales":   p.sales,
            "revenue": round((p.sales or 0) * p.price, 2),
            "stock":   p.stock,
            "rating":  p.rating,
            "price":   p.price,
        }
        for p in products
    ]


@router.get("/analytics/dead-stock")
def analytics_dead_stock(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
):
    products = db.query(Product).filter(
        Product.is_deleted == False,
        Product.stock > 0,
        Product.sales == 0,
    ).order_by(Product.created_at.asc()).limit(limit).all()
    return [
        {
            "id":            str(p.id),
            "title":         p.title,
            "stock":         p.stock,
            "price":         p.price,
            "created_at":    p.created_at,
            "days_alive":    (datetime.now(timezone.utc) - p.created_at).days if p.created_at else None,
            "tied_up_value": round(p.stock * p.price, 2),
        }
        for p in products
    ]


@router.get("/analytics/stock-turnover")
def analytics_stock_turnover(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    limit: int = Query(20, ge=1, le=100),
):
    products = db.query(Product).filter(Product.is_deleted == False, Product.stock > 0).all()
    data = [
        {
            "id":             str(p.id),
            "title":          p.title,
            "sales":          p.sales,
            "stock":          p.stock,
            "price":          p.price,
            "turnover_ratio": round((p.sales or 0) / p.stock, 4) if p.stock else 0,
        }
        for p in products
    ]
    data.sort(key=lambda x: x["turnover_ratio"], reverse=True)
    return data[:limit]


# ─────────────────────────────────────────────
# ORDER INTELLIGENCE
# ─────────────────────────────────────────────

@router.get("/orders/analytics")
def orders_analytics(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    days: int = Query(30, ge=1, le=365),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total     = db.query(Order).filter(Order.created_at >= since, Order.is_deleted == False).count()
    paid      = db.query(Order).filter(Order.status == OrderStatus.paid, Order.created_at >= since).count()
    cancelled = db.query(Order).filter(Order.status == OrderStatus.cancelled, Order.created_at >= since).count()
    shipped   = db.query(Order).filter(Order.status == OrderStatus.shipped, Order.created_at >= since).count()
    completed = db.query(Order).filter(Order.status == OrderStatus.completed, Order.created_at >= since).count()
    return {
        "period_days": days,
        "total":       total,
        "paid":        paid,
        "cancelled":   cancelled,
        "shipped":     shipped,
        "completed":   completed,
        "pending":     total - paid - cancelled - shipped - completed,
    }


@router.get("/orders/revenue")
def orders_revenue(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    days: int = Query(30, ge=1, le=365),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total = db.query(func.sum(Order.total_amount)).filter(Order.status == OrderStatus.paid, Order.created_at >= since).scalar() or 0
    avg   = db.query(func.avg(Order.total_amount)).filter(Order.status == OrderStatus.paid, Order.created_at >= since).scalar() or 0
    count = db.query(Order).filter(Order.status == OrderStatus.paid, Order.created_at >= since).count()
    return {
        "period_days":         days,
        "total_revenue":       round(total, 2),
        "average_order_value": round(avg, 2),
        "paid_orders":         count,
    }


@router.get("/orders/conversion")
def orders_conversion(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    days: int = Query(30, ge=1, le=365),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total     = db.query(Order).filter(Order.created_at >= since, Order.is_deleted == False).count()
    paid      = db.query(Order).filter(Order.status == OrderStatus.paid, Order.created_at >= since).count()
    cancelled = db.query(Order).filter(Order.status == OrderStatus.cancelled, Order.created_at >= since).count()
    return {
        "period_days":           days,
        "total_orders":          total,
        "converted":             paid,
        "conversion_rate_pct":   round((paid / total * 100) if total else 0, 2),
        "cancelled":             cancelled,
        "abandonment_rate_pct":  round((cancelled / total * 100) if total else 0, 2),
    }


# ─────────────────────────────────────────────
# INVENTORY ENGINE
# ─────────────────────────────────────────────

@router.get("/inventory/low-stock")
def inventory_low_stock(db: Session = Depends(get_db), admin=Depends(require_admin)):
    products = db.query(Product).filter(
        Product.stock > 0,
        Product.stock <= Product.low_stock_threshold,
        Product.is_deleted == False,
    ).order_by(Product.stock.asc()).all()
    return [
        {"id": str(p.id), "title": p.title, "stock": p.stock, "threshold": p.low_stock_threshold, "price": p.price}
        for p in products
    ]


@router.get("/inventory/out-of-stock")
def inventory_out_of_stock(db: Session = Depends(get_db), admin=Depends(require_admin)):
    products = db.query(Product).filter(
        Product.stock == 0,
        Product.is_deleted == False,
    ).order_by(Product.updated_at.desc()).all()
    return [
        {"id": str(p.id), "title": p.title, "stock": 0, "price": p.price, "status": p.status}
        for p in products
    ]


@router.get("/inventory/report")
def inventory_report(db: Session = Depends(get_db), admin=Depends(require_admin)):
    total       = db.query(Product).filter(Product.is_deleted == False).count()
    in_stock    = db.query(Product).filter(Product.stock > 0, Product.is_deleted == False).count()
    out_stock   = db.query(Product).filter(Product.stock == 0, Product.is_deleted == False).count()
    low_stock   = db.query(Product).filter(Product.stock > 0, Product.stock <= Product.low_stock_threshold, Product.is_deleted == False).count()
    total_value = db.query(func.sum(Product.stock * Product.price)).filter(Product.is_deleted == False).scalar() or 0
    return {
        "total_products":        total,
        "in_stock":              in_stock,
        "out_of_stock":          out_stock,
        "low_stock":             low_stock,
        "total_inventory_value": round(total_value, 2),
    }


@router.post("/inventory/adjust")
def inventory_adjust(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product_id = payload.get("product_id")
    if not product_id:
        raise HTTPException(400, "product_id required")
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    change    = int(payload.get("quantity_change", 0))
    new_stock = max(0, product.stock + change)
    adj = InventoryAdjustment(
        product_id=product.id,
        adjustment_type=payload.get("type", "manual"),
        quantity_before=product.stock,
        quantity_change=change,
        quantity_after=new_stock,
        note=payload.get("note"),
        reference=payload.get("reference"),
        admin_id=admin.id,
    )
    db.add(adj)
    product.stock    = new_stock
    product.in_stock = new_stock > 0
    db.commit()
    return {"stock_before": adj.quantity_before, "change": change, "stock_after": new_stock}


@router.post("/inventory/incoming")
def inventory_incoming(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product_id = payload.get("product_id")
    quantity   = int(payload.get("quantity", 0))
    if not product_id or quantity <= 0:
        raise HTTPException(400, "product_id and quantity > 0 required")
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    new_stock = product.stock + quantity
    db.add(InventoryAdjustment(
        product_id=product.id,
        adjustment_type="incoming",
        quantity_before=product.stock,
        quantity_change=quantity,
        quantity_after=new_stock,
        note=payload.get("note", "Incoming stock"),
        reference=payload.get("reference"),
        admin_id=admin.id,
    ))
    product.stock    = new_stock
    product.in_stock = new_stock > 0
    db.commit()
    return {"message": "Stock received", "new_stock": new_stock}


# ─────────────────────────────────────────────
# MULTI-STORE MANAGEMENT
# ─────────────────────────────────────────────

@router.get("/stores")
def list_stores(db: Session = Depends(get_db), admin=Depends(require_admin)):
    stores = db.query(Store).order_by(Store.created_at.desc()).all()
    return [
        {
            "id":            str(s.id),
            "name":          s.name,
            "slug":          s.slug,
            "description":   s.description,
            "logo_url":      s.logo_url,
            "contact_email": s.contact_email,
            "is_active":     s.is_active,
            "product_count": db.query(Product).filter(Product.store_id == s.id, Product.is_deleted == False).count(),
            "created_at":    s.created_at,
        }
        for s in stores
    ]


@router.post("/stores", status_code=201)
def create_store(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name required")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if db.query(Store).filter(Store.slug == slug).first():
        raise HTTPException(400, "Store with this name already exists")
    store = Store(
        name=name, slug=slug,
        description=payload.get("description"),
        logo_url=payload.get("logo_url"),
        banner_url=payload.get("banner_url"),
        contact_email=payload.get("contact_email"),
        contact_phone=payload.get("contact_phone"),
        address=payload.get("address"),
        is_active=payload.get("is_active", True),
    )
    db.add(store)
    _log(db, admin, "create", "store", store.id)
    db.commit()
    db.refresh(store)
    return {"id": str(store.id), "slug": store.slug, "message": "Store created"}


@router.patch("/stores/{store_id}")
def update_store(store_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(404, "Store not found")
    for key, value in payload.items():
        if hasattr(store, key) and key not in ("id", "slug", "created_at"):
            setattr(store, key, value)
    _log(db, admin, "update", "store", store_id, meta=payload)
    db.commit()
    return {"message": "Store updated"}


@router.delete("/stores/{store_id}")
def delete_store(store_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(404, "Store not found")
    product_count = db.query(Product).filter(Product.store_id == store_id, Product.is_deleted == False).count()
    if product_count > 0:
        raise HTTPException(400, f"Cannot delete store with {product_count} active products. Reassign or delete them first.")
    _log(db, admin, "delete", "store", store_id)
    db.delete(store)
    db.commit()
    return {"message": "Store deleted"}


# ─────────────────────────────────────────────
# AUDIT LOGS
# ─────────────────────────────────────────────

@router.get("/logs")
def get_audit_logs(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if action:
        query = query.filter(AuditLog.action == action)
    total = query.count()
    logs  = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total,
        "page":  page,
        "results": [
            {
                "id":          str(log.id),
                "admin_id":    str(log.admin_id) if log.admin_id else None,
                "action":      log.action,
                "entity_type": log.entity_type,
                "entity_id":   log.entity_id,
                "before":      log.before,
                "after":       log.after,
                "meta":        log.meta,
                "created_at":  log.created_at,
            }
            for log in logs
        ],
    }


@router.get("/logs/{entity_id}")
def get_entity_logs(entity_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    logs = db.query(AuditLog).filter(AuditLog.entity_id == entity_id).order_by(AuditLog.created_at.desc()).all()
    return [
        {
            "id":          str(log.id),
            "action":      log.action,
            "entity_type": log.entity_type,
            "before":      log.before,
            "after":       log.after,
            "meta":        log.meta,
            "created_at":  log.created_at,
        }
        for log in logs
    ]


# ─────────────────────────────────────────────
# SECURITY — PASSWORD VERIFY
# ─────────────────────────────────────────────

@router.post("/verify-password")
def verify_admin_password(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Confirm admin password before any destructive action."""
    password = payload.get("password", "")
    if not password:
        raise HTTPException(400, "password required")
    admin_user = db.query(User).filter(User.id == admin.id).first()
    if not verify_password(password, admin_user.hashed_password):
        raise HTTPException(403, "Password incorrect")
    return {"verified": True}


# ─────────────────────────────────────────────
# PRODUCT STATUS / ORDER SHORTCUTS (existing)
# ─────────────────────────────────────────────

@router.post("/products/{product_id}/status")
def update_product_status(
    product_id: str, payload: dict,
    db: Session = Depends(get_db), admin=Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    try:
        product.status = ProductStatus(payload.get("status")).value
    except Exception:
        raise HTTPException(400, "Invalid product status")
    db.commit()
    return {"message": "Product status updated"}


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    order.status = OrderStatus.cancelled
    db.commit()
    return {"message": "Order cancelled"}


@router.post("/orders/{order_id}/shipping")
def update_shipping_status(
    order_id: str, payload: dict,
    db: Session = Depends(get_db), admin=Depends(require_admin),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status != OrderStatus.paid:
        raise HTTPException(400, "Cannot ship order before payment is approved")
    try:
        order.shipping_status = ShippingStatus(payload.get("status"))
    except Exception:
        raise HTTPException(400, "Invalid shipping status")
    db.commit()
    return {"message": "Shipping status updated"}


# ═══════════════════════════════════════════════════════════════
# ⚙️  ADMIN STORE RESET — FULL NUCLEAR CONTROL
#
#  All destructive endpoints require:
#  1. POST /admin/verify-password first → get verified=True
#  2. Pass confirm: true in the body
#  3. Are fully logged in AuditLog
# ═══════════════════════════════════════════════════════════════


@router.get("/store-reset/preview")
def store_reset_preview(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Returns counts of everything that WOULD be deleted by a full store reset.
    Call this before showing the admin the confirmation dialog.
    """
    return {
        "products":          db.query(Product).count(),
        "product_images":    db.query(ProductImage).count(),
        "product_variants":  db.query(ProductVariant).count(),
        "orders":            db.query(Order).count(),
        "order_items":       db.query(OrderItem).count(),
        "order_returns":     db.query(OrderReturn).count(),
        "order_notes":       db.query(OrderNote).count(),
        "payments":          db.query(Payment).count(),
        "payment_proofs":    db.query(PaymentProof).count(),
        "payment_history":   db.query(PaymentStatusHistory).count(),
        "bulk_uploads":      db.query(BulkUpload).count(),
        "inventory_logs":    db.query(InventoryAdjustment).count(),
        "reviews":           db.query(Review).count(),
        "carts":             db.query(Cart).count(),
        "wishlists":         db.query(Wishlist).count(),
        "notifications":     db.query(Notification).count(),
        "coupons":           db.query(Coupon).count(),
        "wallet_txns":       db.query(WalletTransaction).count(),
        "recently_viewed":   db.query(RecentlyViewed).count(),
        "audit_logs":        db.query(AuditLog).count(),
        "warning":           "⚠️  This operation is IRREVERSIBLE. All data above will be permanently deleted.",
    }


@router.post("/store-reset/products-only")
def reset_products_only(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Hard-deletes ALL products, images, variants, bulk uploads, inventory logs.
    Orders and users are untouched.
    Requires: { confirm: true }
    """
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")

    counts = {}
    counts["inventory_adjustments"] = db.query(InventoryAdjustment).delete(synchronize_session=False)
    counts["bulk_uploads"]           = db.query(BulkUpload).delete(synchronize_session=False)
    counts["product_variants"]       = db.query(ProductVariant).delete(synchronize_session=False)
    counts["product_images"]         = db.query(ProductImage).delete(synchronize_session=False)
    counts["products"]               = db.query(Product).delete(synchronize_session=False)

    _log(db, admin, "store_reset_products_only", "system", "all", meta=counts)
    db.commit()
    return {"message": "All products permanently deleted", "deleted": counts}


@router.post("/store-reset/orders-only")
def reset_orders_only(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Hard-deletes ALL orders and related payment/order data.
    Products and users are untouched.
    Requires: { confirm: true }
    """
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")

    counts = {}
    counts["payment_status_history"] = db.query(PaymentStatusHistory).delete(synchronize_session=False)
    counts["payment_proofs"]         = db.query(PaymentProof).delete(synchronize_session=False)
    counts["payments"]               = db.query(Payment).delete(synchronize_session=False)
    counts["order_notes"]            = db.query(OrderNote).delete(synchronize_session=False)
    counts["order_returns"]          = db.query(OrderReturn).delete(synchronize_session=False)
    counts["order_tracking"]         = db.query(OrderTracking).delete(synchronize_session=False)
    counts["order_items"]            = db.query(OrderItem).delete(synchronize_session=False)
    counts["orders"]                 = db.query(Order).delete(synchronize_session=False)

    _log(db, admin, "store_reset_orders_only", "system", "all", meta=counts)
    db.commit()
    return {"message": "All orders and payments permanently deleted", "deleted": counts}


@router.post("/store-reset/users-data")
def reset_users_data(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Clears all user-generated data: carts, wishlists, notifications,
    reviews, recently viewed, wallet transactions.
    Does NOT delete user accounts or orders.
    Requires: { confirm: true }
    """
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")

    counts = {}
    counts["recently_viewed"]   = db.query(RecentlyViewed).delete(synchronize_session=False)
    counts["notifications"]     = db.query(Notification).delete(synchronize_session=False)
    counts["wallet_txns"]       = db.query(WalletTransaction).delete(synchronize_session=False)
    counts["coupon_usages"]     = db.query(CouponUsage).delete(synchronize_session=False)
    counts["reviews"]           = db.query(Review).delete(synchronize_session=False)
    counts["cart_items"]        = db.query(CartItem).delete(synchronize_session=False)
    counts["carts"]             = db.query(Cart).delete(synchronize_session=False)
    counts["wishlists"]         = db.query(Wishlist).delete(synchronize_session=False)

    _log(db, admin, "store_reset_users_data", "system", "all", meta=counts)
    db.commit()
    return {"message": "All user-generated data cleared", "deleted": counts}


@router.post("/store-reset/audit-logs")
def reset_audit_logs(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Clears audit logs. Useful after a dev/test reset.
    Requires: { confirm: true }
    """
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")
    count = db.query(AuditLog).delete(synchronize_session=False)
    db.commit()
    # Log the log-clear itself (ironic but useful)
    _log(db, admin, "reset_audit_logs", "system", "all", meta={"deleted": count})
    db.commit()
    return {"message": "Audit logs cleared", "deleted": count}


@router.post("/store-reset/full")
def full_store_reset(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    ☢️  NUCLEAR OPTION — Wipes EVERYTHING except user accounts.
    Deletes all products, orders, payments, reviews, carts, wishlists,
    notifications, coupons, wallet transactions, audit logs, bulk uploads.

    Requires: { confirm: true, confirm_phrase: "RESET EVERYTHING" }
    """
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")
    if payload.get("confirm_phrase") != "RESET EVERYTHING":
        raise HTTPException(400, 'confirm_phrase must be exactly "RESET EVERYTHING"')

    counts = {}

    # ── User-generated data ──
    counts["recently_viewed"]        = db.query(RecentlyViewed).delete(synchronize_session=False)
    counts["notifications"]          = db.query(Notification).delete(synchronize_session=False)
    counts["wallet_transactions"]    = db.query(WalletTransaction).delete(synchronize_session=False)
    counts["coupon_usages"]          = db.query(CouponUsage).delete(synchronize_session=False)
    counts["coupons"]                = db.query(Coupon).delete(synchronize_session=False)
    counts["reviews"]                = db.query(Review).delete(synchronize_session=False)
    counts["cart_items"]             = db.query(CartItem).delete(synchronize_session=False)
    counts["carts"]                  = db.query(Cart).delete(synchronize_session=False)
    counts["wishlists"]              = db.query(Wishlist).delete(synchronize_session=False)

    # ── Payments ──
    counts["payment_status_history"] = db.query(PaymentStatusHistory).delete(synchronize_session=False)
    counts["payment_proofs"]         = db.query(PaymentProof).delete(synchronize_session=False)
    counts["payments"]               = db.query(Payment).delete(synchronize_session=False)

    # ── Orders ──
    counts["order_notes"]            = db.query(OrderNote).delete(synchronize_session=False)
    counts["order_returns"]          = db.query(OrderReturn).delete(synchronize_session=False)
    counts["order_tracking"]         = db.query(OrderTracking).delete(synchronize_session=False)
    counts["order_items"]            = db.query(OrderItem).delete(synchronize_session=False)
    counts["orders"]                 = db.query(Order).delete(synchronize_session=False)

    # ── Products ──
    counts["inventory_adjustments"]  = db.query(InventoryAdjustment).delete(synchronize_session=False)
    counts["bulk_uploads"]           = db.query(BulkUpload).delete(synchronize_session=False)
    counts["product_variants"]       = db.query(ProductVariant).delete(synchronize_session=False)
    counts["product_images"]         = db.query(ProductImage).delete(synchronize_session=False)
    counts["products"]               = db.query(Product).delete(synchronize_session=False)

    # ── Audit logs ──
    counts["audit_logs"]             = db.query(AuditLog).delete(synchronize_session=False)

    db.commit()

    # Write one final log entry after the wipe
    _log(db, admin, "full_store_reset", "system", "ALL", meta={
        "deleted": counts,
        "performed_by": admin.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    db.commit()

    return {
        "message":    "☢️  Full store reset completed. All data wiped except user accounts.",
        "deleted":    counts,
        "total_rows": sum(counts.values()),
    }


@router.post("/store-reset/restore-stock")
def restore_all_stock(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Sets all products back to a given stock level.
    Useful after a test reset to make all products available again.
    Requires: { confirm: true, stock: 100 }
    """
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")
    stock = int(payload.get("stock", 100))
    if stock < 0:
        raise HTTPException(400, "stock must be >= 0")
    count = db.query(Product).filter(Product.is_deleted == False).update(
        {"stock": stock, "in_stock": stock > 0},
        synchronize_session=False,
    )
    _log(db, admin, "restore_all_stock", "system", "all", meta={"stock": stock, "products_updated": count})
    db.commit()
    return {"message": f"All {count} products set to stock={stock}", "updated": count}


@router.post("/store-reset/deactivate-all-products")
def deactivate_all_products(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Sets all non-deleted products to inactive. Requires: { confirm: true }"""
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")
    count = db.query(Product).filter(Product.is_deleted == False).update(
        {"status": "inactive"}, synchronize_session=False
    )
    _log(db, admin, "deactivate_all_products", "system", "all", meta={"count": count})
    db.commit()
    return {"message": f"{count} products deactivated", "updated": count}


@router.post("/store-reset/activate-all-products")
def activate_all_products(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Sets all non-deleted products to active. Requires: { confirm: true }"""
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")
    count = db.query(Product).filter(Product.is_deleted == False).update(
        {"status": "active"}, synchronize_session=False
    )
    _log(db, admin, "activate_all_products", "system", "all", meta={"count": count})
    db.commit()
    return {"message": f"{count} products activated", "updated": count}


@router.delete("/store-reset/cancelled-orders")
def purge_cancelled_orders(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Permanently deletes all cancelled orders and their payments.
    Safe to run periodically to keep DB clean.
    Requires: { confirm: true }
    """
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")

    cancelled_ids = [str(o.id) for o in db.query(Order.id).filter(Order.status == OrderStatus.cancelled).all()]
    if not cancelled_ids:
        return {"message": "No cancelled orders found", "deleted": 0}

    counts = {}
    counts["payment_status_history"] = db.query(PaymentStatusHistory).join(Payment).filter(Payment.order_id.in_(cancelled_ids)).delete(synchronize_session=False)
    counts["payment_proofs"]         = db.query(PaymentProof).join(Payment).filter(Payment.order_id.in_(cancelled_ids)).delete(synchronize_session=False)
    counts["payments"]               = db.query(Payment).filter(Payment.order_id.in_(cancelled_ids)).delete(synchronize_session=False)
    counts["order_notes"]            = db.query(OrderNote).filter(OrderNote.order_id.in_(cancelled_ids)).delete(synchronize_session=False)
    counts["order_items"]            = db.query(OrderItem).filter(OrderItem.order_id.in_(cancelled_ids)).delete(synchronize_session=False)
    counts["orders"]                 = db.query(Order).filter(Order.id.in_(cancelled_ids)).delete(synchronize_session=False)

    _log(db, admin, "purge_cancelled_orders", "system", "all", meta={**counts, "order_ids_count": len(cancelled_ids)})
    db.commit()
    return {"message": f"Purged {len(cancelled_ids)} cancelled orders", "deleted": counts}


# ─────────────────────────────────────────────
# USERS MANAGEMENT
# ─────────────────────────────────────────────

@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    search: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    query = db.query(User)
    if search:
        q = f"%{search}%"
        query = query.filter(
            User.email.ilike(q) | User.full_name.ilike(q)
        )
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total":   total,
        "page":    page,
        "results": [
            {
                "id":         str(u.id),
                "email":      u.email,
                "full_name":  u.full_name,
                "role":       u.role,
                "is_active":  u.is_active,
                "created_at": u.created_at,
            }
            for u in users
        ],
    }


@router.post("/users/{user_id}/disable")
def disable_user(user_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.role == "admin":
        raise HTTPException(400, "Cannot disable admin accounts")
    user.is_active = False
    _log(db, admin, "disable_user", "user", user_id)
    db.commit()
    return {"message": "User disabled"}


@router.post("/users/{user_id}/enable")
def enable_user(user_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_active = True
    _log(db, admin, "enable_user", "user", user_id)
    db.commit()
    return {"message": "User enabled"}


@router.post("/users/{user_id}/role")
def change_role(user_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    new_role = payload.get("role")
    if new_role not in ("user", "admin"):
        raise HTTPException(400, "role must be 'user' or 'admin'")
    old_role = user.role
    user.role = new_role
    _log(db, admin, "change_role", "user", user_id, before={"role": old_role}, after={"role": new_role})
    db.commit()
    return {"message": f"Role changed to {new_role}"}