import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import (
    Order,
    Payment,
    User,
    Product,
    PaymentStatus,
    ShippingStatus,
)

router = APIRouter(prefix="/orders", tags=["orders"])

UPLOAD_DIR = "uploads/payments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# =====================================================
# USER: CREATE ORDER
# =====================================================
@router.post("", status_code=201)
def create_order(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = payload.get("items")
    total_amount = payload.get("total_amount")
    address_id = payload.get("address_id")  # Retrieve address_id

    if not items or not total_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing order data",
        )

    # Ensure address_id exists and is valid
    if not address_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Address ID is required",
        )

    products_to_update = []

    for item in items:
        product_id = item.get("product_id")
        quantity = item.get("quantity", 0)

        if not product_id or quantity <= 0:
            raise HTTPException(400, "Invalid item data")

        product = (
            db.query(Product)
            .filter(Product.id == product_id)
            .with_for_update()
            .first()
        )

        if not product:
            raise HTTPException(404, f"Product {product_id} not found")

        if product.stock < quantity:
            raise HTTPException(
                400, f"Insufficient stock for {product.title}"
            )

        products_to_update.append((product, quantity))

    order = Order(
        user_id=user.id,
        items=items,
        total_amount=total_amount,
        payment_status=PaymentStatus.on_hold,
        shipping_status=ShippingStatus.created,
        address_id=address_id,  # Store address_id with the order
    )

    db.add(order)

    for product, quantity in products_to_update:
        product.stock -= quantity
        product.in_stock = product.stock > 0

    db.commit()
    db.refresh(order)

    return {
        "order_id": order.id,
        "payment_status": order.payment_status.value,
    }


# =====================================================
# USER: ORDER DETAIL
# =====================================================
@router.get("/{order_id}")
def user_order_detail(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(404, "Order not found")

    if order.user_id != user.id:
        raise HTTPException(403, "Not authorized")

    return {
        "id": order.id,
        "items": order.items,
        "total_amount": order.total_amount,
        "payment_status": order.payment_status.value,
        "shipping_status": order.shipping_status.value,
        "tracking_number": order.tracking_number,
        "created_at": order.created_at,
    }


# =====================================================
# USER: UPLOAD PAYMENT PROOF
# =====================================================
@router.post("/{order_id}/payment-proof")
def submit_payment_proof(
    order_id: str,
    proof: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(404, "Order not found")

    if order.user_id != user.id:
        raise HTTPException(403, "Not your order")

    if order.payment_status != PaymentStatus.on_hold:
        raise HTTPException(
            400, "Payment already submitted or processed"
        )

    ext = os.path.splitext(proof.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(proof.file.read())

    payment = Payment(
        order_id=order.id,
        proof_url=f"/{UPLOAD_DIR}/{filename}",
        status=PaymentStatus.payment_submitted,
    )

    order.payment_status = PaymentStatus.payment_submitted

    db.add(payment)
    db.commit()

    return {"message": "Payment proof submitted successfully"}


# =====================================================
# USER: MY ORDERS
# =====================================================
@router.get("/my")
def my_orders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    orders = db.query(Order).filter(Order.user_id == user.id).all()

    return [
        {
            "id": o.id,
            "total_amount": o.total_amount,
            "payment_status": o.payment_status.value,
            "shipping_status": o.shipping_status.value,
            "tracking_number": o.tracking_number,
            "created_at": o.created_at,
        }
        for o in orders
    ]


# =====================================================
# ADMIN: UPDATE ORDER (STRICT FLOW)
# =====================================================
@router.post("/admin/{order_id}/update")
def admin_update_order(
    order_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(404, "Order not found")

    payment_status = payload.get("status")
    shipping_status = payload.get("shipping_status")
    tracking_number = payload.get("tracking_number")

    # ---- PAYMENT REVIEW ----
    if payment_status:
        if order.payment_status != PaymentStatus.payment_submitted:
            raise HTTPException(
                400,
                "Payment can only be reviewed after proof submission",
            )

        try:
            new_status = PaymentStatus(payment_status)
        except ValueError:
            raise HTTPException(400, "Invalid payment status")

        if new_status not in (
            PaymentStatus.payment_received,
            PaymentStatus.rejected,
        ):
            raise HTTPException(
                400,
                "Admin can only approve or reject payment",
            )

        # 🔥 STOCK ROLLBACK ON REJECTION
        if new_status == PaymentStatus.rejected:
            for item in order.items:
                product_id = item.get("product_id")
                quantity = item.get("quantity", 0)

                product = (
                    db.query(Product)
                    .filter(Product.id == product_id)
                    .with_for_update()
                    .first()
                )

                if product:
                    product.stock += quantity
                    product.in_stock = product.stock > 0

        order.payment_status = new_status

        if order.payment:
            order.payment.status = new_status

    # ---- SHIPPING ----
    if shipping_status:
        if order.payment_status != PaymentStatus.payment_received:
            raise HTTPException(
                400,
                "Cannot ship before payment approval",
            )

        try:
            order.shipping_status = ShippingStatus(shipping_status)
        except ValueError:
            raise HTTPException(400, "Invalid shipping status")

    # ---- TRACKING ----
    if tracking_number is not None:
        order.tracking_number = tracking_number

    db.commit()

    return {"message": "Order updated successfully"}
