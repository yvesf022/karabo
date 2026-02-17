from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import Optional
from datetime import datetime, timedelta

from app.database import get_db
from app.dependencies import require_admin
from app.models import (
    Product, ProductStatus, Order, OrderStatus, ShippingStatus,
    Payment, PaymentStatus, User, AuditLog, InventoryAdjustment,
    Store,
)
from app.passwords import verify_password

router = APIRouter(prefix="/admin", tags=["admin"])


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@router.get("/dashboard")
def admin_dashboard(db: Session = Depends(get_db), admin=Depends(require_admin)):
    total_products = db.query(Product).filter(Product.is_deleted == False).count()
    active_products = db.query(Product).filter(Product.status == "active", Product.is_deleted == False).count()
    total_orders = db.query(Order).count()
    paid_orders = db.query(Order).filter(Order.status == OrderStatus.paid).count()
    total_revenue = db.query(func.sum(Order.total_amount)).filter(Order.status == OrderStatus.paid).scalar() or 0
    low_stock = db.query(Product).filter(
        Product.stock > 0, Product.stock <= Product.low_stock_threshold, Product.is_deleted == False
    ).count()
    out_of_stock = db.query(Product).filter(Product.stock == 0, Product.is_deleted == False).count()
    total_users = db.query(User).filter(User.role == "user").count()

    return {
        "total_products": total_products,
        "active_products": active_products,
        "total_orders": total_orders,
        "paid_orders": paid_orders,
        "total_revenue": round(total_revenue, 2),
        "low_stock_count": low_stock,
        "out_of_stock_count": out_of_stock,
        "total_users": total_users,
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
    since = datetime.utcnow() - timedelta(days=days)
    revenue = db.query(func.sum(Order.total_amount)).filter(
        Order.status == OrderStatus.paid, Order.created_at >= since
    ).scalar() or 0
    orders_count = db.query(Order).filter(Order.created_at >= since).count()
    paid_count = db.query(Order).filter(Order.status == OrderStatus.paid, Order.created_at >= since).count()
    new_products = db.query(Product).filter(Product.created_at >= since, Product.is_deleted == False).count()
    new_users = db.query(User).filter(User.created_at >= since, User.role == "user").count()
    return {
        "period_days": days,
        "revenue": round(revenue, 2),
        "orders": orders_count,
        "paid_orders": paid_count,
        "conversion_rate": round((paid_count / orders_count * 100) if orders_count else 0, 2),
        "new_products": new_products,
        "new_users": new_users,
    }


@router.get("/analytics/revenue")
def analytics_revenue(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    days: int = Query(30, ge=1, le=365),
):
    since = datetime.utcnow() - timedelta(days=days)
    # Daily revenue breakdown
    rows = db.execute(
        __import__("sqlalchemy").text("""
            SELECT DATE(created_at) as day, SUM(total_amount) as revenue, COUNT(*) as orders
            FROM orders
            WHERE status = 'paid' AND created_at >= :since
            GROUP BY DATE(created_at)
            ORDER BY day ASC
        """),
        {"since": since}
    ).fetchall()
    total = sum(r.revenue for r in rows)
    return {
        "total_revenue": round(total, 2),
        "period_days": days,
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
    products = db.query(Product).filter(
        Product.is_deleted == False
    ).order_by(Product.sales.desc()).limit(limit).all()
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "sales": p.sales,
            "revenue": round((p.sales or 0) * p.price, 2),
            "stock": p.stock,
            "rating": p.rating,
            "price": p.price,
        }
        for p in products
    ]


@router.get("/analytics/dead-stock")
def analytics_dead_stock(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    days_no_sale: int = Query(60, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """Products with stock > 0 but zero sales or very old."""
    products = db.query(Product).filter(
        Product.is_deleted == False,
        Product.stock > 0,
        Product.sales == 0,
    ).order_by(Product.created_at.asc()).limit(limit).all()
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "stock": p.stock,
            "price": p.price,
            "created_at": p.created_at,
            "days_alive": (datetime.utcnow() - p.created_at.replace(tzinfo=None)).days if p.created_at else None,
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
    """Products ranked by sales-to-stock ratio (turnover)."""
    products = db.query(Product).filter(
        Product.is_deleted == False, Product.stock > 0
    ).all()
    data = []
    for p in products:
        turnover = round((p.sales or 0) / p.stock, 4) if p.stock else 0
        data.append({
            "id": str(p.id),
            "title": p.title,
            "sales": p.sales,
            "stock": p.stock,
            "price": p.price,
            "turnover_ratio": turnover,
        })
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
    since = datetime.utcnow() - timedelta(days=days)
    total = db.query(Order).filter(Order.created_at >= since).count()
    paid = db.query(Order).filter(Order.status == OrderStatus.paid, Order.created_at >= since).count()
    cancelled = db.query(Order).filter(Order.status == OrderStatus.cancelled, Order.created_at >= since).count()
    shipped = db.query(Order).filter(Order.status == OrderStatus.shipped, Order.created_at >= since).count()
    completed = db.query(Order).filter(Order.status == OrderStatus.completed, Order.created_at >= since).count()
    return {
        "period_days": days,
        "total": total,
        "paid": paid,
        "cancelled": cancelled,
        "shipped": shipped,
        "completed": completed,
        "pending": total - paid - cancelled - shipped - completed,
    }


@router.get("/orders/revenue")
def orders_revenue(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    days: int = Query(30, ge=1, le=365),
):
    since = datetime.utcnow() - timedelta(days=days)
    total = db.query(func.sum(Order.total_amount)).filter(
        Order.status == OrderStatus.paid, Order.created_at >= since
    ).scalar() or 0
    avg = db.query(func.avg(Order.total_amount)).filter(
        Order.status == OrderStatus.paid, Order.created_at >= since
    ).scalar() or 0
    count = db.query(Order).filter(Order.status == OrderStatus.paid, Order.created_at >= since).count()
    return {
        "period_days": days,
        "total_revenue": round(total, 2),
        "average_order_value": round(avg, 2),
        "paid_orders": count,
    }


@router.get("/orders/conversion")
def orders_conversion(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
    days: int = Query(30, ge=1, le=365),
):
    since = datetime.utcnow() - timedelta(days=days)
    total = db.query(Order).filter(Order.created_at >= since).count()
    paid = db.query(Order).filter(Order.status == OrderStatus.paid, Order.created_at >= since).count()
    cancelled = db.query(Order).filter(Order.status == OrderStatus.cancelled, Order.created_at >= since).count()
    conversion = round((paid / total * 100) if total else 0, 2)
    abandonment = round((cancelled / total * 100) if total else 0, 2)
    return {
        "period_days": days,
        "total_orders": total,
        "converted": paid,
        "conversion_rate_pct": conversion,
        "cancelled": cancelled,
        "abandonment_rate_pct": abandonment,
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
    total = db.query(Product).filter(Product.is_deleted == False).count()
    in_stock = db.query(Product).filter(Product.stock > 0, Product.is_deleted == False).count()
    out_of_stock = db.query(Product).filter(Product.stock == 0, Product.is_deleted == False).count()
    low_stock = db.query(Product).filter(
        Product.stock > 0, Product.stock <= Product.low_stock_threshold, Product.is_deleted == False
    ).count()
    total_value = db.query(func.sum(Product.stock * Product.price)).filter(Product.is_deleted == False).scalar() or 0
    return {
        "total_products": total,
        "in_stock": in_stock,
        "out_of_stock": out_of_stock,
        "low_stock": low_stock,
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
    change = int(payload.get("quantity_change", 0))
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
    product.stock = new_stock
    product.in_stock = new_stock > 0
    db.commit()
    return {"stock_before": adj.quantity_before, "change": change, "stock_after": new_stock}


@router.post("/inventory/incoming")
def inventory_incoming(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Record incoming stock (purchase order, restocking)."""
    product_id = payload.get("product_id")
    quantity = int(payload.get("quantity", 0))
    if not product_id or quantity <= 0:
        raise HTTPException(400, "product_id and quantity > 0 required")
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    new_stock = product.stock + quantity
    adj = InventoryAdjustment(
        product_id=product.id,
        adjustment_type="incoming",
        quantity_before=product.stock,
        quantity_change=quantity,
        quantity_after=new_stock,
        note=payload.get("note", "Incoming stock"),
        reference=payload.get("reference"),
        admin_id=admin.id,
    )
    db.add(adj)
    product.stock = new_stock
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
            "id": str(s.id), "name": s.name, "slug": s.slug,
            "description": s.description, "logo_url": s.logo_url,
            "contact_email": s.contact_email, "is_active": s.is_active,
            "created_at": s.created_at,
        }
        for s in stores
    ]


@router.post("/stores")
def create_store(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name required")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if db.query(Store).filter(Store.slug == slug).first():
        raise HTTPException(400, "Store with this name already exists")
    store = Store(
        name=name,
        slug=slug,
        description=payload.get("description"),
        logo_url=payload.get("logo_url"),
        banner_url=payload.get("banner_url"),
        contact_email=payload.get("contact_email"),
        contact_phone=payload.get("contact_phone"),
        address=payload.get("address"),
        is_active=payload.get("is_active", True),
    )
    db.add(store)
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
    db.commit()
    return {"message": "Store updated"}


@router.delete("/stores/{store_id}")
def delete_store(store_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(404, "Store not found")
    product_count = db.query(Product).filter(Product.store_id == store_id, Product.is_deleted == False).count()
    if product_count > 0:
        raise HTTPException(400, f"Cannot delete store with {product_count} active products. Reassign them first.")
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
    logs = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total,
        "page": page,
        "results": [
            {
                "id": str(log.id),
                "admin_id": str(log.admin_id) if log.admin_id else None,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "before": log.before,
                "after": log.after,
                "meta": log.meta,
                "created_at": log.created_at,
            }
            for log in logs
        ],
    }


@router.get("/logs/{entity_id}")
def get_entity_logs(entity_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    logs = db.query(AuditLog).filter(AuditLog.entity_id == entity_id).order_by(AuditLog.created_at.desc()).all()
    return [
        {
            "id": str(log.id),
            "action": log.action,
            "entity_type": log.entity_type,
            "before": log.before,
            "after": log.after,
            "meta": log.meta,
            "created_at": log.created_at,
        }
        for log in logs
    ]


# ─────────────────────────────────────────────
# ENTERPRISE SAFETY
# ─────────────────────────────────────────────

@router.post("/verify-password")
def verify_admin_password(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Confirm admin password before destructive actions."""
    password = payload.get("password", "")
    if not password:
        raise HTTPException(400, "password required")
    admin_user = db.query(User).filter(User.id == admin.id).first()
    if not verify_password(password, admin_user.hashed_password):
        raise HTTPException(403, "Password incorrect")
    return {"verified": True}


# ─────────────────────────────────────────────
# EXISTING ROUTES (KEPT)
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