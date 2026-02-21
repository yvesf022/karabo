"""
app/routes/admin.py
Central admin API: dashboard, analytics, inventory, store-reset, orders, users, stores, audit logs.
Every route is protected by require_admin.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import datetime, timezone, timedelta
from typing import Optional
import calendar

from app.database import get_db
from app.models import (
    User, Product, ProductImage, Order, OrderStatus, Payment, PaymentStatus,
    AuditLog, BulkUpload, Store,
)
from app.dependencies import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _month_start():
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _get_stats(db: Session) -> dict:
    """Reusable stats block used by dashboard and overview analytics."""
    total_products   = db.query(Product).filter(Product.is_deleted == False).count()
    active_products  = db.query(Product).filter(Product.status == "active", Product.is_deleted == False).count()
    total_orders     = db.query(Order).filter(Order.is_deleted == False).count()
    paid_orders      = db.query(Order).filter(Order.status == "paid", Order.is_deleted == False).count()
    pending_payments = db.query(Payment).filter(Payment.status == "pending").count()
    low_stock_products = db.query(Product).filter(
        Product.stock > 0,
        Product.stock <= Product.low_stock_threshold,
        Product.is_deleted == False,
    ).count()

    total_revenue = db.query(func.sum(Order.total_amount)).filter(
        Order.status.in_(["paid", "completed", "shipped"]),
        Order.is_deleted == False,
    ).scalar() or 0.0

    revenue_this_month = db.query(func.sum(Order.total_amount)).filter(
        Order.status.in_(["paid", "completed", "shipped"]),
        Order.is_deleted == False,
        Order.created_at >= _month_start(),
    ).scalar() or 0.0

    return {
        "total_products":     total_products,
        "active_products":    active_products,
        "total_orders":       total_orders,
        "paid_orders":        paid_orders,
        "pending_payments":   pending_payments,
        "low_stock_products": low_stock_products,
        "total_revenue":      round(total_revenue, 2),
        "revenue_this_month": round(revenue_this_month, 2),
    }


# ─────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────

@router.get("/dashboard", dependencies=[Depends(require_admin)])
def dashboard(db: Session = Depends(get_db)):
    """Main dashboard KPIs."""
    return _get_stats(db)


# ─────────────────────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────────────────────

@router.get("/analytics/overview", dependencies=[Depends(require_admin)])
def analytics_overview(db: Session = Depends(get_db)):
    return _get_stats(db)


@router.get("/analytics/revenue", dependencies=[Depends(require_admin)])
def analytics_revenue(days: int = Query(30, ge=7, le=365), db: Session = Depends(get_db)):
    """Revenue per day for the last `days` days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date(Order.created_at).label("date"),
            func.sum(Order.total_amount).label("revenue"),
            func.count(Order.id).label("orders"),
        )
        .filter(
            Order.status.in_(["paid", "completed", "shipped"]),
            Order.is_deleted == False,
            Order.created_at >= since,
        )
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at))
        .all()
    )
    return [
        {"date": str(r.date), "revenue": round(float(r.revenue or 0), 2), "orders": r.orders}
        for r in rows
    ]


@router.get("/analytics/top-products", dependencies=[Depends(require_admin)])
def analytics_top_products(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Top products by sales count."""
    products = (
        db.query(Product)
        .filter(Product.is_deleted == False)
        .order_by(Product.sales.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "product_id": str(p.id),
            "title":      p.title,
            "sales":      p.sales or 0,
            "revenue":    round((p.sales or 0) * p.price, 2),
            "stock":      p.stock,
            "price":      p.price,
            "main_image": next((img.image_url for img in p.images if img.is_primary), None)
                          or (p.images[0].image_url if p.images else None),
        }
        for p in products
    ]


@router.get("/analytics/dead-stock", dependencies=[Depends(require_admin)])
def analytics_dead_stock(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """Products with stock > 0 but 0 sales."""
    products = (
        db.query(Product)
        .filter(Product.is_deleted == False, Product.stock > 0, Product.sales == 0)
        .order_by(Product.created_at.asc())
        .limit(limit)
        .all()
    )
    now = datetime.now(timezone.utc)
    return [
        {
            "product_id":  str(p.id),
            "title":       p.title,
            "stock":       p.stock,
            "price":       p.price,
            "days_listed": (now - p.created_at.replace(tzinfo=timezone.utc) if p.created_at else timedelta(0)).days,
        }
        for p in products
    ]


@router.get("/analytics/stock-turnover", dependencies=[Depends(require_admin)])
def analytics_stock_turnover(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """Stock turnover rate = sales / (stock + sales) * 10."""
    products = (
        db.query(Product)
        .filter(Product.is_deleted == False, Product.sales > 0)
        .order_by(Product.sales.desc())
        .limit(limit)
        .all()
    )
    now = datetime.now(timezone.utc)
    return [
        {
            "product_id":    str(p.id),
            "title":         p.title,
            "sales":         p.sales or 0,
            "stock":         p.stock,
            "turnover_rate": round((p.sales or 0) / max(p.stock + (p.sales or 0), 1) * 10, 2),
            "days_in_stock": (now - p.created_at.replace(tzinfo=timezone.utc) if p.created_at else timedelta(0)).days,
        }
        for p in products
    ]


@router.get("/orders/analytics", dependencies=[Depends(require_admin)])
def orders_analytics(db: Session = Depends(get_db)):
    """Order breakdown by status."""
    total_orders = db.query(Order).filter(Order.is_deleted == False).count()
    total_revenue = db.query(func.sum(Order.total_amount)).filter(
        Order.status.in_(["paid", "completed", "shipped"]), Order.is_deleted == False
    ).scalar() or 0

    by_status_rows = (
        db.query(Order.status, func.count(Order.id), func.sum(Order.total_amount))
        .filter(Order.is_deleted == False)
        .group_by(Order.status)
        .all()
    )
    by_status = {}
    for status, count, revenue in by_status_rows:
        by_status[status.value if hasattr(status, "value") else str(status)] = {
            "count":      count,
            "revenue":    round(float(revenue or 0), 2),
            "percentage": round(count / max(total_orders, 1) * 100, 1),
        }

    return {
        "total_orders":   total_orders,
        "total_revenue":  round(float(total_revenue), 2),
        "paid_orders":    by_status.get("paid", {}).get("count", 0),
        "pending_orders": by_status.get("pending", {}).get("count", 0),
        "cancelled_orders": by_status.get("cancelled", {}).get("count", 0),
        "by_status":      by_status,
    }


@router.get("/orders/revenue", dependencies=[Depends(require_admin)])
def orders_revenue(db: Session = Depends(get_db)):
    return analytics_revenue(db=db)


@router.get("/orders/conversion", dependencies=[Depends(require_admin)])
def orders_conversion(db: Session = Depends(get_db)):
    total    = db.query(Order).filter(Order.is_deleted == False).count()
    paid     = db.query(Order).filter(Order.status.in_(["paid", "completed"]), Order.is_deleted == False).count()
    pending  = db.query(Order).filter(Order.status == "pending", Order.is_deleted == False).count()
    cancelled = db.query(Order).filter(Order.status == "cancelled", Order.is_deleted == False).count()
    return {
        "total": total,
        "paid": paid,
        "pending": pending,
        "cancelled": cancelled,
        "conversion_rate": round(paid / max(total, 1) * 100, 1),
    }


# ─────────────────────────────────────────────────────────────
# INVENTORY
# ─────────────────────────────────────────────────────────────

@router.get("/inventory/low-stock", dependencies=[Depends(require_admin)])
def low_stock(limit: int = 50, db: Session = Depends(get_db)):
    products = (
        db.query(Product)
        .filter(
            Product.is_deleted == False,
            Product.stock > 0,
            Product.stock <= Product.low_stock_threshold,
        )
        .order_by(Product.stock.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id":         str(p.id),
            "title":      p.title,
            "stock":      p.stock,
            "threshold":  p.low_stock_threshold,
            "price":      p.price,
            "category":   p.category,
            "main_image": next((img.image_url for img in p.images if img.is_primary), None)
                          or (p.images[0].image_url if p.images else None),
        }
        for p in products
    ]


@router.get("/inventory/out-of-stock", dependencies=[Depends(require_admin)])
def out_of_stock(limit: int = 100, db: Session = Depends(get_db)):
    products = (
        db.query(Product)
        .filter(Product.is_deleted == False, Product.stock == 0)
        .order_by(Product.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id":       str(p.id),
            "title":    p.title,
            "stock":    p.stock,
            "price":    p.price,
            "category": p.category,
            "status":   p.status,
            "main_image": next((img.image_url for img in p.images if img.is_primary), None)
                          or (p.images[0].image_url if p.images else None),
        }
        for p in products
    ]


@router.get("/inventory/report", dependencies=[Depends(require_admin)])
def inventory_report(db: Session = Depends(get_db)):
    total       = db.query(Product).filter(Product.is_deleted == False).count()
    in_stock    = db.query(Product).filter(Product.is_deleted == False, Product.stock > 0).count()
    out         = db.query(Product).filter(Product.is_deleted == False, Product.stock == 0).count()
    low         = db.query(Product).filter(
        Product.is_deleted == False, Product.stock > 0, Product.stock <= Product.low_stock_threshold
    ).count()
    total_value = db.query(func.sum(Product.stock * Product.price)).filter(Product.is_deleted == False).scalar() or 0
    return {
        "total_products":   total,
        "in_stock":         in_stock,
        "out_of_stock":     out,
        "low_stock":        low,
        "total_inventory_value": round(float(total_value), 2),
    }


@router.post("/inventory/adjust", dependencies=[Depends(require_admin)])
def adjust_inventory(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    from app.models import InventoryAdjustment
    product_id = payload.get("product_id")
    quantity   = int(payload.get("quantity", 0))
    product    = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before        = product.stock
    product.stock = max(0, product.stock + quantity)
    product.in_stock = product.stock > 0
    db.add(InventoryAdjustment(
        product_id=product.id,
        adjustment_type="manual",
        quantity_before=before,
        quantity_change=quantity,
        quantity_after=product.stock,
        note=payload.get("note"),
        admin_id=admin.id,
    ))
    db.commit()
    return {"message": "Inventory adjusted", "stock": product.stock}


@router.post("/inventory/incoming", dependencies=[Depends(require_admin)])
def incoming_inventory(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    return adjust_inventory(payload, db=db, admin=admin)


# ─────────────────────────────────────────────────────────────
# STORES
# ─────────────────────────────────────────────────────────────

@router.get("/stores", dependencies=[Depends(require_admin)])
def list_stores(db: Session = Depends(get_db)):
    stores = db.query(Store).order_by(Store.created_at.desc()).all()
    return [
        {
            "id":          str(s.id),
            "name":        s.name,
            "slug":        s.slug,
            "description": s.description,
            "logo_url":    s.logo_url,
            "is_active":   s.is_active,
            "created_at":  s.created_at,
            "product_count": db.query(Product).filter(Product.store_id == s.id, Product.is_deleted == False).count(),
        }
        for s in stores
    ]


@router.post("/stores", dependencies=[Depends(require_admin)], status_code=201)
def create_store(payload: dict, db: Session = Depends(get_db)):
    import re
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    slug = payload.get("slug") or re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
    if db.query(Store).filter(Store.slug == slug).first():
        raise HTTPException(400, f"Slug '{slug}' already exists")
    store = Store(
        name=name, slug=slug,
        description=payload.get("description"),
        logo_url=payload.get("logo_url"),
        is_active=payload.get("is_active", True),
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    return {"id": str(store.id), "name": store.name, "slug": store.slug}


@router.patch("/stores/{store_id}", dependencies=[Depends(require_admin)])
def update_store(store_id: str, payload: dict, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(404, "Store not found")
    for k, v in payload.items():
        if hasattr(store, k):
            setattr(store, k, v)
    db.commit()
    return {"message": "Store updated"}


@router.delete("/stores/{store_id}", dependencies=[Depends(require_admin)])
def delete_store(store_id: str, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(404, "Store not found")
    db.delete(store)
    db.commit()
    return {"message": "Store deleted"}


# ─────────────────────────────────────────────────────────────
# ORDERS (admin cancel + shipping)
# ─────────────────────────────────────────────────────────────

@router.post("/orders/{order_id}/cancel", dependencies=[Depends(require_admin)])
def admin_cancel_order(order_id: str, payload: dict, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id, Order.is_deleted == False).first()
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status == OrderStatus.cancelled:
        raise HTTPException(400, "Order is already cancelled")
    order.status     = OrderStatus.cancelled
    order.updated_at = datetime.now(timezone.utc)
    for payment in order.payments:
        if payment.status in (PaymentStatus.pending, PaymentStatus.on_hold):
            payment.status = PaymentStatus.rejected
    db.commit()
    return {"message": "Order cancelled", "order_id": order_id}


@router.post("/orders/{order_id}/shipping", dependencies=[Depends(require_admin)])
def admin_update_shipping(order_id: str, payload: dict, db: Session = Depends(get_db)):
    from app.models import ShippingStatus
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        order.shipping_status = ShippingStatus(payload.get("status"))
    except Exception:
        raise HTTPException(400, "Invalid shipping status")
    order.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Shipping updated", "shipping_status": order.shipping_status}


# ─────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────

@router.get("/users", dependencies=[Depends(require_admin)])
def list_users(
    search: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if search:
        q = f"%{search}%"
        from sqlalchemy import or_
        query = query.filter(or_(User.email.ilike(q), User.full_name.ilike(q)))
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    total = query.count()
    users = query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total,
        "results": [
            {
                "id":         str(u.id),
                "email":      u.email,
                "full_name":  u.full_name,
                "phone":      u.phone,
                "role":       u.role,
                "is_active":  u.is_active,
                "avatar_url": u.avatar_url,
                "created_at": u.created_at,
                "order_count": db.query(Order).filter(Order.user_id == u.id, Order.is_deleted == False).count(),
            }
            for u in users
        ],
    }


@router.post("/users/{user_id}/disable", dependencies=[Depends(require_admin)])
def disable_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_active = False
    db.commit()
    return {"id": str(user.id), "status": "disabled"}


@router.post("/users/{user_id}/enable", dependencies=[Depends(require_admin)])
def enable_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_active = True
    db.commit()
    return {"id": str(user.id), "status": "enabled"}


@router.post("/users/{user_id}/role", dependencies=[Depends(require_admin)])
def change_role(user_id: str, payload: dict, db: Session = Depends(get_db)):
    role = payload.get("role") if isinstance(payload, dict) else None
    if role not in {"user", "admin"}:
        raise HTTPException(400, "Role must be 'user' or 'admin'")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.role = role
    db.commit()
    return {"id": str(user.id), "role": user.role}


@router.delete("/users/{user_id}", dependencies=[Depends(require_admin)])
def delete_user(user_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if str(user.id) == str(admin.id):
        raise HTTPException(400, "Cannot delete your own admin account")
    if user.role == "admin":
        raise HTTPException(400, "Cannot delete admin users")
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}


# ─────────────────────────────────────────────────────────────
# AUDIT LOGS
# ─────────────────────────────────────────────────────────────

@router.get("/logs", dependencies=[Depends(require_admin)])
def get_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    entity_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id":          str(l.id),
            "action":      l.action,
            "entity_type": l.entity_type,
            "entity_id":   l.entity_id,
            "before":      l.before,
            "after":       l.after,
            "meta":        l.meta,
            "created_at":  l.created_at,
            "admin_email": l.admin.email if l.admin else None,
        }
        for l in logs
    ]


@router.get("/logs/{entity_id}", dependencies=[Depends(require_admin)])
def get_entity_logs(entity_id: str, db: Session = Depends(get_db)):
    logs = db.query(AuditLog).filter(AuditLog.entity_id == entity_id).order_by(AuditLog.created_at.desc()).all()
    return [
        {
            "id":          str(l.id),
            "action":      l.action,
            "entity_type": l.entity_type,
            "before":      l.before,
            "after":       l.after,
            "created_at":  l.created_at,
            "admin_email": l.admin.email if l.admin else None,
        }
        for l in logs
    ]


# ─────────────────────────────────────────────────────────────
# VERIFY PASSWORD (for dangerous actions)
# ─────────────────────────────────────────────────────────────

@router.post("/verify-password", dependencies=[Depends(require_admin)])
def verify_password_check(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    from app.passwords import verify_password
    password = payload.get("password", "")
    if not verify_password(password, admin.hashed_password):
        raise HTTPException(401, "Incorrect password")
    return {"verified": True}


# ─────────────────────────────────────────────────────────────
# STORE RESET
# All operations are DESTRUCTIVE — require careful use
# ─────────────────────────────────────────────────────────────

@router.get("/store-reset/preview", dependencies=[Depends(require_admin)])
def store_reset_preview(db: Session = Depends(get_db)):
    """Show what each reset operation would affect."""
    return {
        "products":        db.query(Product).filter(Product.is_deleted == False).count(),
        "deleted_products": db.query(Product).filter(Product.is_deleted == True).count(),
        "orders":          db.query(Order).filter(Order.is_deleted == False).count(),
        "cancelled_orders": db.query(Order).filter(Order.status == "cancelled", Order.is_deleted == False).count(),
        "users":           db.query(User).filter(User.role != "admin").count(),
        "payments":        db.query(Payment).count(),
        "audit_logs":      db.query(AuditLog).count(),
    }


@router.post("/store-reset/products-only", dependencies=[Depends(require_admin)])
def reset_products_only(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Hard-delete ALL products (including images). Cannot be undone."""
    count = db.query(Product).count()
    db.query(Product).delete(synchronize_session=False)
    db.add(AuditLog(admin_id=admin.id, action="store_reset_products", entity_type="store", entity_id="all",
                    meta={"deleted": count}))
    db.commit()
    return {"message": f"Permanently deleted {count} products", "deleted": count}


@router.post("/store-reset/orders-only", dependencies=[Depends(require_admin)])
def reset_orders_only(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Hard-delete ALL orders and payments. Cannot be undone."""
    order_count   = db.query(Order).count()
    payment_count = db.query(Payment).count()
    db.query(Payment).delete(synchronize_session=False)
    db.query(Order).delete(synchronize_session=False)
    db.add(AuditLog(admin_id=admin.id, action="store_reset_orders", entity_type="store", entity_id="all",
                    meta={"orders": order_count, "payments": payment_count}))
    db.commit()
    return {"message": f"Deleted {order_count} orders and {payment_count} payments"}


@router.post("/store-reset/users-data", dependencies=[Depends(require_admin)])
def reset_users_data(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Delete all non-admin users."""
    count = db.query(User).filter(User.role != "admin").count()
    db.query(User).filter(User.role != "admin").delete(synchronize_session=False)
    db.add(AuditLog(admin_id=admin.id, action="store_reset_users", entity_type="store", entity_id="all",
                    meta={"deleted": count}))
    db.commit()
    return {"message": f"Deleted {count} non-admin users"}


@router.post("/store-reset/audit-logs", dependencies=[Depends(require_admin)])
def reset_audit_logs(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Clear all audit logs."""
    count = db.query(AuditLog).count()
    db.query(AuditLog).delete(synchronize_session=False)
    db.commit()
    return {"message": f"Deleted {count} audit log entries"}


@router.post("/store-reset/full", dependencies=[Depends(require_admin)])
def store_reset_full(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Full store reset: products, orders, payments, non-admin users. CANNOT BE UNDONE."""
    product_count = db.query(Product).count()
    order_count   = db.query(Order).count()
    payment_count = db.query(Payment).count()
    user_count    = db.query(User).filter(User.role != "admin").count()

    db.query(Payment).delete(synchronize_session=False)
    db.query(Order).delete(synchronize_session=False)
    db.query(Product).delete(synchronize_session=False)
    db.query(User).filter(User.role != "admin").delete(synchronize_session=False)

    db.add(AuditLog(admin_id=admin.id, action="store_reset_full", entity_type="store", entity_id="all",
                    meta={"products": product_count, "orders": order_count,
                          "payments": payment_count, "users": user_count}))
    db.commit()
    return {
        "message": "Full store reset completed",
        "deleted": {
            "products": product_count,
            "orders":   order_count,
            "payments": payment_count,
            "users":    user_count,
        },
    }


@router.post("/store-reset/restore-stock", dependencies=[Depends(require_admin)])
def restore_stock(threshold: int = Query(100), db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Set all out-of-stock products back to threshold units."""
    count = db.query(Product).filter(Product.is_deleted == False, Product.stock == 0).update(
        {"stock": threshold, "in_stock": True}, synchronize_session=False
    )
    db.commit()
    return {"message": f"Restocked {count} products to {threshold} units", "updated": count}


@router.post("/store-reset/deactivate-all-products", dependencies=[Depends(require_admin)])
def deactivate_all_products(db: Session = Depends(get_db), admin=Depends(require_admin)):
    count = db.query(Product).filter(Product.is_deleted == False).update(
        {"status": "inactive"}, synchronize_session=False
    )
    db.commit()
    return {"message": f"Deactivated {count} products", "updated": count}


@router.post("/store-reset/activate-all-products", dependencies=[Depends(require_admin)])
def activate_all_products(db: Session = Depends(get_db), admin=Depends(require_admin)):
    count = db.query(Product).filter(Product.is_deleted == False).update(
        {"status": "active"}, synchronize_session=False
    )
    db.commit()
    return {"message": f"Activated {count} products", "updated": count}


@router.delete("/store-reset/cancelled-orders", dependencies=[Depends(require_admin)])
def purge_cancelled_orders(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Permanently delete all cancelled orders."""
    orders = db.query(Order).filter(Order.status == OrderStatus.cancelled).all()
    count = len(orders)
    for o in orders:
        db.delete(o)
    db.add(AuditLog(admin_id=admin.id, action="purge_cancelled_orders", entity_type="order", entity_id="all",
                    meta={"count": count}))
    db.commit()
    return {"message": f"Purged {count} cancelled orders", "deleted": count}


@router.post("/store-reset/reset-sales", dependencies=[Depends(require_admin)])
def reset_sales(payload: dict = None, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Reset sales count. Pass ids[] to reset specific products, or empty for all."""
    payload = payload or {}
    ids = payload.get("ids")
    query = db.query(Product).filter(Product.is_deleted == False)
    if ids:
        query = query.filter(Product.id.in_(ids))
    count = query.update({"sales": 0}, synchronize_session=False)
    db.commit()
    return {"message": f"Reset sales for {count} products", "updated": count}


@router.post("/store-reset/reset-ratings", dependencies=[Depends(require_admin)])
def reset_ratings(payload: dict = None, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Reset ratings. Pass ids[] to reset specific products, or empty for all."""
    payload = payload or {}
    ids = payload.get("ids")
    query = db.query(Product).filter(Product.is_deleted == False)
    if ids:
        query = query.filter(Product.id.in_(ids))
    count = query.update({"rating": 0, "rating_number": 0}, synchronize_session=False)
    db.commit()
    return {"message": f"Reset ratings for {count} products", "updated": count}


@router.delete("/store-reset/hard-delete-all", dependencies=[Depends(require_admin)])
def hard_delete_all_products(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Permanently hard-delete ALL products including soft-deleted ones."""
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed")
    count = db.query(Product).count()
    db.query(Product).delete(synchronize_session=False)
    db.add(AuditLog(admin_id=admin.id, action="hard_delete_all_products", entity_type="product", entity_id="all",
                    meta={"count": count}))
    db.commit()
    return {"message": f"Permanently deleted {count} products", "deleted": count}