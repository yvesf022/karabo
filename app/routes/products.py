from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import Optional, List
import csv
import io
import json
import copy
import re
from datetime import datetime

from app.database import get_db
from app.models import (
    Product, ProductImage, ProductVariant,
    InventoryAdjustment, AuditLog, BulkUpload, BulkUploadStatus,
)
from app.dependencies import require_admin
from app.uploads.service import handle_upload

router = APIRouter(prefix="/products", tags=["products"])


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _log(db: Session, admin, action: str, entity_type: str, entity_id: str,
         before=None, after=None, meta=None):
    db.add(AuditLog(
        admin_id=admin.id if admin else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=before,
        after=after,
        meta=meta,
    ))


def _product_snapshot(p: Product) -> dict:
    return {
        "title": p.title, "status": p.status,
        "price": p.price, "stock": p.stock,
        "is_deleted": p.is_deleted,
    }


def _serialize_product(p: Product) -> dict:
    return {
        "id": str(p.id),
        "title": p.title,
        "short_description": p.short_description,
        "description": p.description,
        "price": p.price,
        "compare_price": p.compare_price,
        "brand": p.brand,
        "store": p.store,
        "store_id": str(p.store_id) if p.store_id else None,
        "parent_asin": p.parent_asin,
        "rating": p.rating,
        "rating_number": p.rating_number,
        "sales": p.sales,
        "category": p.category,
        "main_category": p.main_category,
        "categories": p.categories,
        "features": p.features,
        "details": p.details,
        "stock": p.stock,
        "in_stock": p.stock > 0,
        "low_stock_threshold": p.low_stock_threshold,
        "status": p.status,
        "is_deleted": p.is_deleted,
        "main_image": p.images[0].image_url if p.images else None,
        "images": [{"id": str(img.id), "url": img.image_url, "position": img.position, "is_primary": img.is_primary} for img in p.images],
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


# ─────────────────────────────────────────────
# PUBLIC: LIST PRODUCTS
# ─────────────────────────────────────────────

@router.get("")
def list_products(
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    category: Optional[str] = None,
    main_category: Optional[str] = None,
    brand: Optional[str] = None,
    store: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock: Optional[bool] = None,
    min_rating: Optional[float] = None,
    sort: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    query = db.query(Product).filter(
        Product.status == "active",
        Product.is_deleted == False,
    )

    if search:
        q = f"%{search}%"
        query = query.filter(or_(Product.title.ilike(q), Product.short_description.ilike(q)))
    if category:
        query = query.filter(Product.category == category)
    if main_category:
        query = query.filter(Product.main_category == main_category)
    if brand:
        query = query.filter(Product.brand == brand)
    if store:
        query = query.filter(Product.store == store)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    if in_stock is not None:
        query = query.filter(Product.stock > 0 if in_stock else Product.stock <= 0)
    if min_rating is not None:
        query = query.filter(Product.rating >= min_rating)

    sort_map = {
        "price_asc": Product.price.asc(),
        "price_desc": Product.price.desc(),
        "rating": Product.rating.desc(),
        "newest": Product.created_at.desc(),
        "sales": Product.sales.desc(),
    }
    query = query.order_by(sort_map.get(sort, Product.created_at.desc()))

    total = query.count()
    products = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "results": [
            {
                "id": str(p.id),
                "title": p.title,
                "short_description": p.short_description,
                "price": p.price,
                "compare_price": p.compare_price,
                "brand": p.brand,
                "store": p.store,
                "rating": p.rating,
                "rating_number": p.rating_number,
                "sales": p.sales,
                "category": p.category,
                "main_category": p.main_category,
                "stock": p.stock,
                "in_stock": p.stock > 0,
                "main_image": p.images[0].image_url if p.images else None,
                "images": [img.image_url for img in p.images],
                "created_at": p.created_at,
            }
            for p in products
        ],
    }


# ─────────────────────────────────────────────
# PUBLIC: GET SINGLE PRODUCT
# ─────────────────────────────────────────────

@router.get("/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.status == "active",
        Product.is_deleted == False,
    ).first()
    if not product:
        raise HTTPException(404, "Product not found")
    return _serialize_product(product)


# ─────────────────────────────────────────────
# ADMIN: LIST ALL PRODUCTS (WITH FULL FILTERS)
# ─────────────────────────────────────────────

@router.get("/admin/list", dependencies=[Depends(require_admin)])
def admin_list_products(
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    status: Optional[str] = None,
    stock: Optional[str] = None,         # "low", "out", "in"
    rating: Optional[float] = None,
    store: Optional[str] = None,
    brand: Optional[str] = None,
    category: Optional[str] = None,
    include_deleted: bool = False,
    sort: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    query = db.query(Product)
    if not include_deleted:
        query = query.filter(Product.is_deleted == False)

    if search:
        q = f"%{search}%"
        query = query.filter(or_(Product.title.ilike(q), Product.brand.ilike(q), Product.sku.ilike(q)))
    if status:
        query = query.filter(Product.status == status)
    if store:
        query = query.filter(Product.store == store)
    if brand:
        query = query.filter(Product.brand == brand)
    if category:
        query = query.filter(Product.category == category)
    if rating is not None:
        query = query.filter(Product.rating >= rating)
    if stock == "out":
        query = query.filter(Product.stock == 0)
    elif stock == "low":
        query = query.filter(Product.stock > 0, Product.stock <= Product.low_stock_threshold)
    elif stock == "in":
        query = query.filter(Product.stock > 0)

    sort_map = {
        "price_asc": Product.price.asc(),
        "price_desc": Product.price.desc(),
        "stock_asc": Product.stock.asc(),
        "stock_desc": Product.stock.desc(),
        "newest": Product.created_at.desc(),
        "oldest": Product.created_at.asc(),
    }
    query = query.order_by(sort_map.get(sort, Product.created_at.desc()))

    total = query.count()
    products = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "results": [_serialize_product(p) for p in products],
    }


# ─────────────────────────────────────────────
# ADMIN: CREATE PRODUCT
# ─────────────────────────────────────────────

@router.post("", dependencies=[Depends(require_admin)])
def create_product(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = Product(**payload)
    product.status = payload.get("status", "active")
    product.in_stock = product.stock > 0
    db.add(product)
    db.flush()
    _log(db, admin, "create", "product", product.id, after=_product_snapshot(product))
    db.commit()
    db.refresh(product)
    return {"id": str(product.id)}


# ─────────────────────────────────────────────
# ADMIN: UPDATE PRODUCT
# ─────────────────────────────────────────────

@router.patch("/admin/{product_id}", dependencies=[Depends(require_admin)])
def update_product(product_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before = _product_snapshot(product)
    for key, value in payload.items():
        if hasattr(product, key):
            setattr(product, key, value)
    product.in_stock = product.stock > 0
    _log(db, admin, "update", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    return {"message": "Product updated"}


# ─────────────────────────────────────────────
# ADMIN: PRODUCT LIFECYCLE
# ─────────────────────────────────────────────

@router.delete("/{product_id}", dependencies=[Depends(require_admin)])
def soft_delete_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before = _product_snapshot(product)
    product.is_deleted = True
    product.deleted_at = datetime.utcnow()
    product.status = "inactive"
    _log(db, admin, "delete", "product", product_id, before=before)
    db.commit()
    return {"message": "Product soft-deleted"}


@router.delete("/{product_id}/hard", dependencies=[Depends(require_admin)])
def hard_delete_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    _log(db, admin, "hard_delete", "product", product_id, before=_product_snapshot(product))
    db.delete(product)
    db.commit()
    return {"message": "Product permanently deleted"}


@router.post("/{product_id}/duplicate", dependencies=[Depends(require_admin)])
def duplicate_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    original = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not original:
        raise HTTPException(404, "Product not found")

    new_product = Product(
        title=f"{original.title} (Copy)",
        short_description=original.short_description,
        description=original.description,
        sku=f"{original.sku}-copy" if original.sku else None,
        brand=original.brand,
        price=original.price,
        compare_price=original.compare_price,
        rating=0,
        rating_number=0,
        sales=0,
        category=original.category,
        main_category=original.main_category,
        categories=original.categories,
        specs=original.specs,
        details=original.details,
        features=original.features,
        stock=original.stock,
        in_stock=original.in_stock,
        low_stock_threshold=original.low_stock_threshold,
        store=original.store,
        store_id=original.store_id,
        status="draft",
        is_deleted=False,
    )
    db.add(new_product)
    db.flush()

    for img in original.images:
        db.add(ProductImage(product_id=new_product.id, image_url=img.image_url, position=img.position))

    _log(db, admin, "duplicate", "product", new_product.id, meta={"source_id": str(product_id)})
    db.commit()
    db.refresh(new_product)
    return {"id": str(new_product.id), "message": "Product duplicated"}


@router.post("/{product_id}/archive", dependencies=[Depends(require_admin)])
def archive_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before = _product_snapshot(product)
    product.status = "archived"
    _log(db, admin, "archive", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    return {"message": "Product archived"}


@router.post("/{product_id}/restore", dependencies=[Depends(require_admin)])
def restore_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before = _product_snapshot(product)
    product.is_deleted = False
    product.deleted_at = None
    product.status = "active"
    _log(db, admin, "restore", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    return {"message": "Product restored"}


@router.post("/{product_id}/publish", dependencies=[Depends(require_admin)])
def publish_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before = _product_snapshot(product)
    product.status = "active"
    _log(db, admin, "publish", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    return {"message": "Product published"}


@router.post("/{product_id}/draft", dependencies=[Depends(require_admin)])
def draft_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before = _product_snapshot(product)
    product.status = "draft"
    _log(db, admin, "draft", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    return {"message": "Product set to draft"}


# ─────────────────────────────────────────────
# ADMIN: BULK OPERATIONS ENGINE
# ─────────────────────────────────────────────

@router.patch("/admin/bulk", dependencies=[Depends(require_admin)])
def bulk_mutate(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """
    Unified bulk mutation endpoint.
    payload: { "ids": [...], "action": "activate|deactivate|archive|discount|category|store", ...fields }
    """
    ids = payload.get("ids", [])
    action = payload.get("action")
    if not ids or not action:
        raise HTTPException(400, "ids and action are required")

    products = db.query(Product).filter(Product.id.in_(ids), Product.is_deleted == False).all()
    if not products:
        raise HTTPException(404, "No products found")

    updated = 0
    for p in products:
        if action == "activate":
            p.status = "active"
        elif action == "deactivate":
            p.status = "inactive"
        elif action == "archive":
            p.status = "archived"
        elif action == "draft":
            p.status = "draft"
        elif action == "discount":
            pct = float(payload.get("discount_percent", 0))
            if 0 < pct < 100:
                p.compare_price = p.price
                p.price = round(p.price * (1 - pct / 100), 2)
        elif action == "category":
            p.category = payload.get("category", p.category)
            p.main_category = payload.get("main_category", p.main_category)
        elif action == "store":
            p.store = payload.get("store", p.store)
        else:
            raise HTTPException(400, f"Unknown action: {action}")
        updated += 1

    _log(db, admin, "bulk_update", "product", "bulk", meta={"action": action, "ids": ids, "count": updated})
    db.commit()
    return {"message": f"Bulk {action} applied", "updated": updated}


@router.delete("/admin/bulk-delete", dependencies=[Depends(require_admin)])
def bulk_delete(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(400, "ids required")
    products = db.query(Product).filter(Product.id.in_(ids), Product.is_deleted == False).all()
    for p in products:
        p.is_deleted = True
        p.deleted_at = datetime.utcnow()
        p.status = "inactive"
    _log(db, admin, "bulk_delete", "product", "bulk", meta={"ids": ids, "count": len(products)})
    db.commit()
    return {"message": "Products soft-deleted", "deleted": len(products)}


@router.delete("/admin/empty-store", dependencies=[Depends(require_admin)])
def empty_store(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Soft-delete ALL products. Requires confirm:true in payload."""
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm:true to proceed")
    count = db.query(Product).filter(Product.is_deleted == False).update(
        {"is_deleted": True, "deleted_at": datetime.utcnow(), "status": "inactive"},
        synchronize_session=False,
    )
    _log(db, admin, "empty_store", "product", "all", meta={"count": count})
    db.commit()
    return {"message": "Store emptied", "deleted": count}


@router.post("/admin/bulk-archive", dependencies=[Depends(require_admin)])
def bulk_archive(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    count = db.query(Product).filter(Product.id.in_(ids)).update({"status": "archived"}, synchronize_session=False)
    db.commit()
    return {"updated": count}


@router.post("/admin/bulk-activate", dependencies=[Depends(require_admin)])
def bulk_activate(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    count = db.query(Product).filter(Product.id.in_(ids)).update({"status": "active"}, synchronize_session=False)
    db.commit()
    return {"updated": count}


@router.post("/admin/bulk-deactivate", dependencies=[Depends(require_admin)])
def bulk_deactivate(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    count = db.query(Product).filter(Product.id.in_(ids)).update({"status": "inactive"}, synchronize_session=False)
    db.commit()
    return {"updated": count}


@router.post("/admin/bulk-discount", dependencies=[Depends(require_admin)])
def bulk_discount(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    pct = float(payload.get("discount_percent", 0))
    if not 0 < pct < 100:
        raise HTTPException(400, "discount_percent must be between 0 and 100")
    products = db.query(Product).filter(Product.id.in_(ids)).all()
    for p in products:
        p.compare_price = p.price
        p.price = round(p.price * (1 - pct / 100), 2)
    db.commit()
    return {"updated": len(products)}


@router.post("/admin/bulk-category", dependencies=[Depends(require_admin)])
def bulk_category(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    category = payload.get("category")
    main_category = payload.get("main_category")
    products = db.query(Product).filter(Product.id.in_(ids)).all()
    for p in products:
        if category:
            p.category = category
        if main_category:
            p.main_category = main_category
    db.commit()
    return {"updated": len(products)}


@router.post("/admin/bulk-store", dependencies=[Depends(require_admin)])
def bulk_store(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    store = payload.get("store")
    if not store:
        raise HTTPException(400, "store is required")
    count = db.query(Product).filter(Product.id.in_(ids)).update({"store": store}, synchronize_session=False)
    db.commit()
    return {"updated": count}


# ─────────────────────────────────────────────
# ADMIN: IMPORT / EXPORT
# ─────────────────────────────────────────────

@router.post("/admin/import-validate", dependencies=[Depends(require_admin)])
async def import_validate(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Validates CSV without importing. Returns row-by-row errors."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be CSV")
    contents = await file.read()
    reader = csv.DictReader(io.StringIO(contents.decode("utf-8")))
    rows = list(reader)
    errors = []
    warnings = []
    for idx, row in enumerate(rows, 1):
        if not row.get("title", "").strip():
            errors.append({"row": idx, "field": "title", "error": "Missing required field"})
        try:
            price = float(row.get("price", 0) or 0)
            if price <= 0:
                warnings.append({"row": idx, "field": "price", "warning": "Price is 0 or missing"})
        except ValueError:
            errors.append({"row": idx, "field": "price", "error": "Invalid number"})
        asin = row.get("parent_asin", "").strip()
        if asin:
            exists = db.query(Product).filter(Product.parent_asin == asin).first()
            if exists:
                warnings.append({"row": idx, "field": "parent_asin", "warning": f"Duplicate ASIN: {asin}"})
    return {
        "total_rows": len(rows),
        "errors": errors,
        "warnings": warnings,
        "valid": len(errors) == 0,
    }


@router.post("/admin/import-preview", dependencies=[Depends(require_admin)])
async def import_preview(file: UploadFile = File(...)):
    """Returns first 10 parsed rows for preview before import."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be CSV")
    contents = await file.read()
    reader = csv.DictReader(io.StringIO(contents.decode("utf-8")))
    rows = list(reader)
    preview = []
    for row in rows[:10]:
        preview.append({
            "title": row.get("title", ""),
            "price": row.get("price", ""),
            "category": row.get("main_category", ""),
            "stock": row.get("stock", ""),
            "parent_asin": row.get("parent_asin", ""),
            "store": row.get("store", ""),
        })
    return {"total_rows": len(rows), "preview": preview}


@router.get("/admin/export", dependencies=[Depends(require_admin)])
def export_products(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    store: Optional[str] = None,
    category: Optional[str] = None,
    include_deleted: bool = False,
):
    """Export products to CSV. Streams the file."""
    query = db.query(Product)
    if not include_deleted:
        query = query.filter(Product.is_deleted == False)
    if status:
        query = query.filter(Product.status == status)
    if store:
        query = query.filter(Product.store == store)
    if category:
        query = query.filter(Product.category == category)
    products = query.order_by(Product.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "title", "sku", "brand", "store", "category", "main_category",
        "price", "compare_price", "stock", "rating", "rating_number", "sales",
        "status", "is_deleted", "created_at"
    ])
    for p in products:
        writer.writerow([
            str(p.id), p.title, p.sku, p.brand, p.store, p.category, p.main_category,
            p.price, p.compare_price, p.stock, p.rating, p.rating_number, p.sales,
            p.status, p.is_deleted, p.created_at,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products_export.csv"},
    )


# ─────────────────────────────────────────────
# ADMIN: VARIANT SYSTEM
# ─────────────────────────────────────────────

@router.get("/{product_id}/variants", dependencies=[Depends(require_admin)])
def list_variants(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    variants = db.query(ProductVariant).filter(
        ProductVariant.product_id == product_id,
        ProductVariant.is_deleted == False,
    ).all()
    return [
        {
            "id": str(v.id),
            "title": v.title,
            "sku": v.sku,
            "attributes": v.attributes,
            "price": v.price,
            "compare_price": v.compare_price,
            "stock": v.stock,
            "in_stock": v.stock > 0,
            "image_url": v.image_url,
            "is_active": v.is_active,
            "created_at": v.created_at,
        }
        for v in variants
    ]


@router.post("/{product_id}/variants", dependencies=[Depends(require_admin)])
def create_variant(product_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    variant = ProductVariant(
        product_id=product_id,
        title=payload.get("title", ""),
        sku=payload.get("sku"),
        attributes=payload.get("attributes", {}),
        price=float(payload.get("price", product.price)),
        compare_price=payload.get("compare_price"),
        stock=int(payload.get("stock", 0)),
        in_stock=int(payload.get("stock", 0)) > 0,
        image_url=payload.get("image_url"),
        is_active=payload.get("is_active", True),
    )
    db.add(variant)
    _log(db, admin, "create", "variant", variant.id, after={"title": variant.title, "price": variant.price})
    db.commit()
    db.refresh(variant)
    return {"id": str(variant.id), "message": "Variant created"}


@router.patch("/variants/{variant_id}", dependencies=[Depends(require_admin)])
def update_variant(variant_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    variant = db.query(ProductVariant).filter(ProductVariant.id == variant_id, ProductVariant.is_deleted == False).first()
    if not variant:
        raise HTTPException(404, "Variant not found")
    for key, value in payload.items():
        if hasattr(variant, key):
            setattr(variant, key, value)
    if "stock" in payload:
        variant.in_stock = variant.stock > 0
    _log(db, admin, "update", "variant", variant_id)
    db.commit()
    return {"message": "Variant updated"}


@router.delete("/variants/{variant_id}", dependencies=[Depends(require_admin)])
def delete_variant(variant_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    variant = db.query(ProductVariant).filter(ProductVariant.id == variant_id).first()
    if not variant:
        raise HTTPException(404, "Variant not found")
    variant.is_deleted = True
    _log(db, admin, "delete", "variant", variant_id)
    db.commit()
    return {"message": "Variant deleted"}


@router.post("/variants/{variant_id}/duplicate", dependencies=[Depends(require_admin)])
def duplicate_variant(variant_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    original = db.query(ProductVariant).filter(ProductVariant.id == variant_id, ProductVariant.is_deleted == False).first()
    if not original:
        raise HTTPException(404, "Variant not found")
    new_v = ProductVariant(
        product_id=original.product_id,
        title=f"{original.title} (Copy)",
        sku=f"{original.sku}-copy" if original.sku else None,
        attributes=original.attributes,
        price=original.price,
        compare_price=original.compare_price,
        stock=original.stock,
        in_stock=original.in_stock,
        image_url=original.image_url,
        is_active=False,
    )
    db.add(new_v)
    _log(db, admin, "duplicate", "variant", new_v.id, meta={"source_id": str(variant_id)})
    db.commit()
    db.refresh(new_v)
    return {"id": str(new_v.id), "message": "Variant duplicated"}


@router.patch("/variants/bulk", dependencies=[Depends(require_admin)])
def bulk_update_variants(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    updates = payload.get("updates", {})
    if not ids or not updates:
        raise HTTPException(400, "ids and updates required")
    variants = db.query(ProductVariant).filter(ProductVariant.id.in_(ids), ProductVariant.is_deleted == False).all()
    for v in variants:
        for key, value in updates.items():
            if hasattr(v, key):
                setattr(v, key, value)
        if "stock" in updates:
            v.in_stock = v.stock > 0
    db.commit()
    return {"updated": len(variants)}


# ─────────────────────────────────────────────
# ADMIN: IMAGE MANAGEMENT
# ─────────────────────────────────────────────

@router.post("/{product_id}/images/bulk", dependencies=[Depends(require_admin)])
def bulk_add_images(product_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Add multiple images at once. payload: { urls: [...] }"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    urls = payload.get("urls", [])
    if not urls:
        raise HTTPException(400, "urls required")
    max_pos = max((img.position for img in product.images), default=-1)
    added = []
    for i, url in enumerate(urls):
        img = ProductImage(product_id=product_id, image_url=url, position=max_pos + i + 1)
        db.add(img)
        added.append(url)
    db.commit()
    return {"added": len(added)}


@router.patch("/images/{image_id}/position", dependencies=[Depends(require_admin)])
def set_image_position(image_id: str, payload: dict, db: Session = Depends(get_db)):
    image = db.query(ProductImage).filter(ProductImage.id == image_id).first()
    if not image:
        raise HTTPException(404, "Image not found")
    image.position = int(payload.get("position", image.position))
    db.commit()
    return {"message": "Position updated"}


@router.patch("/images/{image_id}/set-primary", dependencies=[Depends(require_admin)])
def set_primary_image(image_id: str, db: Session = Depends(get_db)):
    image = db.query(ProductImage).filter(ProductImage.id == image_id).first()
    if not image:
        raise HTTPException(404, "Image not found")
    # Remove primary from all siblings
    db.query(ProductImage).filter(ProductImage.product_id == image.product_id).update({"is_primary": False})
    image.is_primary = True
    image.position = 0
    db.commit()
    return {"message": "Primary image set"}


# ─────────────────────────────────────────────
# ADMIN: PRODUCT ANALYTICS
# ─────────────────────────────────────────────

@router.get("/admin/{product_id}/analytics", dependencies=[Depends(require_admin)])
def product_analytics(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    adj_history = db.query(InventoryAdjustment).filter(
        InventoryAdjustment.product_id == product_id
    ).order_by(InventoryAdjustment.created_at.desc()).limit(20).all()
    return {
        "id": str(product.id),
        "title": product.title,
        "price": product.price,
        "stock": product.stock,
        "sales": product.sales,
        "rating": product.rating,
        "rating_number": product.rating_number,
        "revenue_estimate": round((product.sales or 0) * product.price, 2),
        "inventory_history": [
            {
                "type": a.adjustment_type,
                "before": a.quantity_before,
                "change": a.quantity_change,
                "after": a.quantity_after,
                "note": a.note,
                "created_at": a.created_at,
            }
            for a in adj_history
        ],
    }


# ─────────────────────────────────────────────
# ADMIN: INVENTORY
# ─────────────────────────────────────────────

@router.patch("/{product_id}/inventory", dependencies=[Depends(require_admin)])
def update_product_inventory(product_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    new_stock = int(payload.get("stock", product.stock))
    adj = InventoryAdjustment(
        product_id=product.id,
        adjustment_type=payload.get("type", "manual"),
        quantity_before=product.stock,
        quantity_change=new_stock - product.stock,
        quantity_after=new_stock,
        note=payload.get("note"),
        reference=payload.get("reference"),
        admin_id=admin.id,
    )
    db.add(adj)
    product.stock = new_stock
    product.in_stock = new_stock > 0
    db.commit()
    return {"message": "Inventory updated", "stock": new_stock}


@router.patch("/variants/{variant_id}/inventory", dependencies=[Depends(require_admin)])
def update_variant_inventory(variant_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    variant = db.query(ProductVariant).filter(ProductVariant.id == variant_id).first()
    if not variant:
        raise HTTPException(404, "Variant not found")
    new_stock = int(payload.get("stock", variant.stock))
    adj = InventoryAdjustment(
        product_id=variant.product_id,
        variant_id=variant.id,
        adjustment_type=payload.get("type", "manual"),
        quantity_before=variant.stock,
        quantity_change=new_stock - variant.stock,
        quantity_after=new_stock,
        note=payload.get("note"),
        reference=payload.get("reference"),
        admin_id=admin.id,
    )
    db.add(adj)
    variant.stock = new_stock
    variant.in_stock = new_stock > 0
    db.commit()
    return {"message": "Variant inventory updated", "stock": new_stock}


# ─────────────────────────────────────────────
# ADMIN: BULK UPLOAD (EXISTING — KEPT)
# ─────────────────────────────────────────────

@router.post("/admin/bulk-upload", dependencies=[Depends(require_admin)])
async def bulk_upload_products(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be CSV format")

    upload_record = BulkUpload(filename=file.filename, uploaded_by=admin.id, status=BulkUploadStatus.processing)
    db.add(upload_record)
    db.commit()
    db.refresh(upload_record)

    contents = await file.read()
    csv_reader = csv.DictReader(io.StringIO(contents.decode("utf-8")))
    rows = list(csv_reader)
    upload_record.total_rows = len(rows)
    db.commit()

    successful = 0
    failed = 0
    errors = []

    for idx, row in enumerate(rows, 1):
        try:
            title = row.get("title", "").strip()
            if not title:
                raise ValueError("Missing title")
            parent_asin = row.get("parent_asin", "").strip()
            if parent_asin:
                if db.query(Product).filter(Product.parent_asin == parent_asin).first():
                    raise ValueError("Duplicate parent_asin")
            categories = json.loads(row.get("categories", "[]") or "[]")
            features = json.loads(row.get("features", "[]") or "[]")
            details = json.loads(row.get("details", "{}") or "{}")
            product = Product(
                title=title,
                short_description=row.get("short_description", title)[:200],
                description=row.get("description", ""),
                main_category=row.get("main_category", ""),
                category=categories[0] if categories else "",
                categories=categories,
                price=float(row.get("price", 0) or 0),
                compare_price=float(row.get("compare_price", 0) or 0) or None,
                rating=float(row.get("rating", 0) or 0),
                rating_number=int(row.get("rating_number", 0) or 0),
                features=features,
                details=details,
                store=row.get("store", ""),
                parent_asin=parent_asin,
                stock=int(row.get("stock", 10) or 10),
                in_stock=str(row.get("in_stock", "true")).lower() == "true",
                status="active",
            )
            db.add(product)
            db.flush()
            for pos, url in enumerate([u.strip() for u in row.get("image_urls", "").split(",") if u.strip()][:10]):
                db.add(ProductImage(product_id=product.id, image_url=url, position=pos))
            successful += 1
        except Exception as e:
            failed += 1
            errors.append({"row": idx, "error": str(e)})

    upload_record.successful_rows = successful
    upload_record.failed_rows = failed
    upload_record.errors = errors[:100]
    upload_record.status = (
        BulkUploadStatus.completed if failed == 0 else
        BulkUploadStatus.partial if successful > 0 else
        BulkUploadStatus.failed
    )
    upload_record.completed_at = datetime.utcnow()
    db.commit()
    return {"total": len(rows), "successful": successful, "failed": failed}


@router.get("/admin/bulk-uploads", dependencies=[Depends(require_admin)])
def list_bulk_uploads(db: Session = Depends(get_db)):
    uploads = db.query(BulkUpload).order_by(BulkUpload.started_at.desc()).limit(50).all()
    return [
        {
            "id": str(u.id), "filename": u.filename, "status": u.status,
            "total_rows": u.total_rows, "successful_rows": u.successful_rows,
            "failed_rows": u.failed_rows, "started_at": u.started_at, "completed_at": u.completed_at,
        }
        for u in uploads
    ]