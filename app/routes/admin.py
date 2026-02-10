from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models import Product, ProductStatus, Order, OrderStatus, ShippingStatus

router = APIRouter(prefix="/admin", tags=["admin"])


# =============================
# ADMIN: DASHBOARD STATS
# =============================
@router.get("/dashboard")
def admin_dashboard(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    total_products = db.query(Product).count()
    active_products = (
        db.query(Product)
        .filter(Product.status == ProductStatus.active)
        .count()
    )
    total_orders = db.query(Order).count()
    paid_orders = (
        db.query(Order)
        .filter(Order.status == OrderStatus.paid)  # ✅ FIXED: was order_status
        .count()
    )

    return {
        "total_products": total_products,
        "active_products": active_products,
        "total_orders": total_orders,
        "paid_orders": paid_orders,
    }


# =============================
# ADMIN: UPDATE PRODUCT STATUS
# =============================
@router.post("/products/{product_id}/status")
def update_product_status(
    product_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")

    try:
        product.status = ProductStatus(payload.get("status"))
    except Exception:
        raise HTTPException(400, "Invalid product status")

    db.commit()
    return {"message": "Product status updated"}


# =============================
# ADMIN: UPDATE ORDER STATUS (CANCEL)
# =============================
@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: str,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")

    order.status = OrderStatus.cancelled  # ✅ FIXED: was order_status
    db.commit()

    return {"message": "Order cancelled"}


# =============================
# ADMIN: UPDATE SHIPPING STATUS
# =============================
@router.post("/orders/{order_id}/shipping")
def update_shipping_status(
    order_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")

    if order.status != OrderStatus.paid:  # ✅ FIXED: was order_status
        raise HTTPException(
            400,
            "Cannot ship order before payment is approved",
        )

    try:
        order.shipping_status = ShippingStatus(payload.get("status"))
    except Exception:
        raise HTTPException(400, "Invalid shipping status")

    db.commit()
    return {"message": "Shipping status updated"}
