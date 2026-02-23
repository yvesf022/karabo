from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func, or_
from typing import Optional
import csv
import io
import json
from datetime import datetime, timezone

from app.database import get_db
from app.models import (
    Product, ProductImage, ProductVariant,
    InventoryAdjustment, AuditLog, BulkUpload, BulkUploadStatus, Store,
)
from app.dependencies import require_admin
from app.uploads.service import handle_upload

router = APIRouter(prefix="/products", tags=["products"])


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


def _product_snapshot(p: Product) -> dict:
    return {
        "title": p.title, "status": p.status,
        "price": p.price, "stock": p.stock,
        "is_deleted": p.is_deleted,
    }


def _serialize_product(p: Product, admin: bool = False) -> dict:
    data = {
        "id":                str(p.id),
        "title":             p.title,
        "short_description": p.short_description,
        "description":       p.description,
        "sku":               p.sku,
        "price":             p.price,
        "compare_price":     p.compare_price,
        "brand":             p.brand,
        "store":             p.store,
        "store_id":          str(p.store_id) if p.store_id else None,
        "parent_asin":       p.parent_asin,
        "rating":            p.rating,
        "rating_number":     p.rating_number,
        "sales":             p.sales,
        "category":          p.category,
        "main_category":     p.main_category,
        "categories":        p.categories,
        "features":          p.features,
        "details":           p.details,
        "stock":             p.stock,
        "in_stock":          p.stock > 0,
        "low_stock_threshold": p.low_stock_threshold,
        "status":            p.status,
        "main_image":        next((img.image_url for img in p.images if img.is_primary), None) or (p.images[0].image_url if p.images else None),
        "images":            [{"id": str(img.id), "url": img.image_url, "position": img.position, "is_primary": img.is_primary} for img in p.images],
        "created_at":        p.created_at,
        "updated_at":        p.updated_at,
    }
    if admin:
        data["is_deleted"] = p.is_deleted
        data["deleted_at"] = p.deleted_at
    return data


# ═══════════════════════════════════════════════════════════════
# ⚠️  ROUTE ORDER IS CRITICAL — static routes BEFORE /{product_id}
# ═══════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────
# PUBLIC: LIST PRODUCTS
# ─────────────────────────────────────────────

@router.get("")
def list_products(
    db: Session = Depends(get_db),
    search:        Optional[str]   = None,
    category:      Optional[str]   = None,
    main_category: Optional[str]   = None,
    brand:         Optional[str]   = None,
    store:         Optional[str]   = None,
    store_id:      Optional[str]   = None,
    min_price:     Optional[float] = None,
    max_price:     Optional[float] = None,
    in_stock:      Optional[bool]  = None,
    min_rating:    Optional[float] = None,
    sort:          Optional[str]   = None,
    page:          int = Query(1, ge=1),
    per_page:      int = Query(20, ge=1, le=100),
):
    query = db.query(Product).options(selectinload(Product.images)).filter(
        Product.status == "active",
        Product.is_deleted == False,
    )
    if search:
        q = f"%{search}%"
        query = query.filter(or_(Product.title.ilike(q), Product.short_description.ilike(q), Product.brand.ilike(q)))
    if category:
        query = query.filter(Product.category == category)
    if main_category:
        query = query.filter(Product.main_category == main_category)
    if brand:
        query = query.filter(Product.brand == brand)
    if store:
        query = query.filter(Product.store == store)
    if store_id:
        query = query.filter(Product.store_id == store_id)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    if in_stock is not None:
        query = query.filter(Product.stock > 0 if in_stock else Product.stock <= 0)
    if min_rating is not None:
        query = query.filter(Product.rating >= min_rating)

    sort_map = {
        "price_asc":  Product.price.asc(),
        "price_desc": Product.price.desc(),
        "rating":     Product.rating.desc(),
        "newest":     Product.created_at.desc(),
        "sales":      Product.sales.desc(),
        "random":     func.random(),
        "discount":   (Product.compare_price - Product.price).desc(),
    }
    if sort == "random":
        query = query.order_by(func.random())
    else:
        query = query.order_by(sort_map.get(sort, Product.created_at.desc()))

    total    = query.count()
    products = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    (total + per_page - 1) // per_page,
         "results": [
             {
                 "id":            str(p.id),
                 "title":         p.title,
                 "price":         p.price,
                 "compare_price": p.compare_price,
                 "discount_pct":  round(((p.compare_price - p.price) / p.compare_price) * 100) if p.compare_price and p.compare_price > p.price > 0 else None,
                 "brand":         p.brand,
                 "rating":        p.rating,
                 "rating_number": p.rating_number,
                 "category":      p.category,
                 "stock":         p.stock,
                 "in_stock":      p.stock > 0,
                 "main_image":    getattr(p, "main_image", None) or getattr(p, "image_url", None) or next((img.image_url for img in p.images if img.is_primary), None) or (p.images[0].image_url if p.images else None),
             }
             for p in products
         ],
     }


# ─────────────────────────────────────────────
# ADMIN: LIST PRODUCTS
# ─────────────────────────────────────────────

@router.get("/admin/list", dependencies=[Depends(require_admin)])
def admin_list_products(
    db: Session = Depends(get_db),
    search:          Optional[str]   = None,
    status:          Optional[str]   = None,
    stock:           Optional[str]   = None,
    # Frontend sends low_stock=true / in_stock=false for stock filters
    low_stock:       Optional[bool]  = None,
    in_stock:        Optional[bool]  = None,
    rating:          Optional[float] = None,
    store:           Optional[str]   = None,
    store_id:        Optional[str]   = None,
    brand:           Optional[str]   = None,
    category:        Optional[str]   = None,
    include_deleted: bool = False,
    sort:            Optional[str]   = None,
    # Frontend uses sort_by + sort_dir instead of single sort string
    sort_by:         Optional[str]   = None,
    sort_dir:        Optional[str]   = "desc",
    page:            int = Query(1, ge=1),
    per_page:        int = Query(50, ge=1, le=200),
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
    if store_id:
        query = query.filter(Product.store_id == store_id)
    if brand:
        query = query.filter(Product.brand == brand)
    if category:
        query = query.filter(Product.category == category)
    if rating is not None:
        query = query.filter(Product.rating >= rating)
    if stock == "out" or in_stock is False:
        query = query.filter(Product.stock == 0)
    elif stock == "low" or low_stock is True:
        query = query.filter(Product.stock > 0, Product.stock <= Product.low_stock_threshold)
    elif stock == "in" or in_stock is True:
        query = query.filter(Product.stock > 0)

    # Support both old single-string sort and new sort_by+sort_dir params from frontend
    def _get_order():
        # New-style: sort_by + sort_dir
        if sort_by:
            col_map = {
                "title":      Product.title,
                "price":      Product.price,
                "stock":      Product.stock,
                "sales":      Product.sales,
                "created_at": Product.created_at,
                "rating":     Product.rating,
            }
            col = col_map.get(sort_by, Product.created_at)
            return col.asc() if sort_dir == "asc" else col.desc()
        # Old-style: single sort string
        sort_map = {
            "price_asc":   Product.price.asc(),
            "price_desc":  Product.price.desc(),
            "stock_asc":   Product.stock.asc(),
            "stock_desc":  Product.stock.desc(),
            "newest":      Product.created_at.desc(),
            "oldest":      Product.created_at.asc(),
            "sales":       Product.sales.desc(),
        }
        return sort_map.get(sort, Product.created_at.desc())

    query = query.order_by(_get_order())

    total    = query.count()
    products = query.offset((page - 1) * per_page).limit(per_page).all()

    # Summary counts for admin UI
    stats = {
        "total":       db.query(Product).filter(Product.is_deleted == False).count(),
        "active":      db.query(Product).filter(Product.status == "active", Product.is_deleted == False).count(),
        "draft":       db.query(Product).filter(Product.status == "draft", Product.is_deleted == False).count(),
        "archived":    db.query(Product).filter(Product.status == "archived", Product.is_deleted == False).count(),
        "out_of_stock": db.query(Product).filter(Product.stock == 0, Product.is_deleted == False).count(),
        "deleted":     db.query(Product).filter(Product.is_deleted == True).count(),
    }

    return {
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    (total + per_page - 1) // per_page,
        "stats":    stats,
        "results":  [_serialize_product(p, admin=True) for p in products],
    }


# ─────────────────────────────────────────────
# ADMIN: CREATE PRODUCT
# ─────────────────────────────────────────────

@router.post("", dependencies=[Depends(require_admin)], status_code=201)
def create_product(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    # Validate required fields
    if not payload.get("title", "").strip():
        raise HTTPException(400, "title is required")
    if payload.get("price") is None:
        raise HTTPException(400, "price is required")

    product = Product(
        title             = payload.get("title", "").strip(),
        short_description = payload.get("short_description", ""),
        description       = payload.get("description", ""),
        sku               = payload.get("sku"),
        brand             = payload.get("brand"),
        price             = float(payload.get("price", 0)),
        compare_price     = payload.get("compare_price"),
        category          = payload.get("category", ""),
        main_category     = payload.get("main_category", ""),
        categories        = payload.get("categories", []),
        features          = payload.get("features", []),
        details           = payload.get("details", {}),
        store             = payload.get("store", ""),
        store_id          = payload.get("store_id"),
        parent_asin       = payload.get("parent_asin"),
        stock             = int(payload.get("stock", 0)),
        low_stock_threshold = int(payload.get("low_stock_threshold", 10)),
        status            = payload.get("status", "active"),
        is_deleted        = False,
    )
    product.in_stock = product.stock > 0
    db.add(product)
    db.flush()

    # Add images if provided
    for i, url in enumerate(payload.get("image_urls", [])):
        db.add(ProductImage(product_id=product.id, image_url=url, position=i, is_primary=(i == 0)))

    _log(db, admin, "create", "product", product.id, after=_product_snapshot(product))
    db.commit()
    db.refresh(product)
    return {"id": str(product.id), "message": "Product created"}


# ─────────────────────────────────────────────
# ADMIN: UPDATE PRODUCT
# ─────────────────────────────────────────────

@router.patch("/admin/{product_id}", dependencies=[Depends(require_admin)])
def update_product(product_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before = _product_snapshot(product)

    # Whitelist updatable fields to prevent accidents
    allowed = {
        "title", "short_description", "description", "sku", "brand",
        "price", "compare_price", "category", "main_category", "categories",
        "features", "details", "store", "store_id", "parent_asin",
        "stock", "low_stock_threshold", "status", "rating",
    }
    for key, value in payload.items():
        if key in allowed:
            setattr(product, key, value)

    if "stock" in payload:
        product.in_stock = product.stock > 0

    _log(db, admin, "update", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    db.refresh(product)
    return {"message": "Product updated", "product": _serialize_product(product, admin=True)}


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
    ).order_by(InventoryAdjustment.created_at.desc()).limit(50).all()
    return {
        "id":               str(product.id),
        "title":            product.title,
        "price":            product.price,
        "stock":            product.stock,
        "sales":            product.sales,
        "rating":           product.rating,
        "rating_number":    product.rating_number,
        "revenue_estimate": round((product.sales or 0) * product.price, 2),
        "inventory_history": [
            {
                "id":         str(a.id),
                "type":       a.adjustment_type,
                "before":     a.quantity_before,
                "change":     a.quantity_change,
                "after":      a.quantity_after,
                "note":       a.note,
                "reference":  a.reference,
                "created_at": a.created_at,
            }
            for a in adj_history
        ],
    }


# ─────────────────────────────────────────────
# ADMIN: BULK OPERATIONS
# ─────────────────────────────────────────────

@router.patch("/admin/bulk", dependencies=[Depends(require_admin)])
def bulk_mutate(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids    = payload.get("ids", [])
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
                p.price         = round(p.price * (1 - pct / 100), 2)
        elif action == "category":
            if payload.get("category"):
                p.category = payload["category"]
            if payload.get("main_category"):
                p.main_category = payload["main_category"]
        elif action == "store":
            if payload.get("store"):
                p.store = payload["store"]
            if payload.get("store_id"):
                p.store_id = payload["store_id"]
        elif action == "remove_discount":
            if p.compare_price:
                p.price         = p.compare_price
                p.compare_price = None
        else:
            raise HTTPException(400, f"Unknown action: {action}")
        updated += 1

    _log(db, admin, "bulk_update", "product", "bulk", meta={"action": action, "ids": ids, "count": updated})
    db.commit()
    return {"message": f"Bulk '{action}' applied", "updated": updated}


@router.delete("/admin/bulk-delete", dependencies=[Depends(require_admin)])
def bulk_delete(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(400, "ids required")
    products = db.query(Product).filter(Product.id.in_(ids), Product.is_deleted == False).all()
    for p in products:
        p.is_deleted = True
        p.deleted_at = datetime.now(timezone.utc)
        p.status     = "inactive"
    _log(db, admin, "bulk_delete", "product", "bulk", meta={"ids": ids, "count": len(products)})
    db.commit()
    return {"message": "Products soft-deleted", "deleted": len(products)}


@router.delete("/admin/bulk-hard-delete", dependencies=[Depends(require_admin)])
def bulk_hard_delete(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Permanently delete products — no recovery. Only works on already-soft-deleted products."""
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(400, "ids required")
    if not payload.get("confirm"):
        raise HTTPException(400, "Send confirm: true to proceed with permanent deletion")
    # Allow hard-deleting any product regardless of soft-delete state
    products = db.query(Product).filter(Product.id.in_(ids)).all()
    count    = len(products)
    for p in products:
        db.delete(p)
    _log(db, admin, "bulk_hard_delete", "product", "bulk", meta={"ids": ids, "count": count})
    db.commit()
    return {"message": "Products permanently deleted", "deleted": count}


@router.delete("/admin/empty-store", dependencies=[Depends(require_admin)])
def empty_store(
    confirm: Optional[bool] = Query(None),
    payload: dict = None,
    db: Session = Depends(get_db),
    admin = Depends(require_admin),
):
    """Soft-deletes all products. Accepts confirm=true as query param OR JSON body."""
    # Accept confirm from query param (frontend) or JSON body (Postman/API)
    payload = payload or {}
    confirmed = confirm is True or payload.get("confirm") is True
    if not confirmed:
        raise HTTPException(400, "Send confirm=true to proceed")
    count = db.query(Product).filter(Product.is_deleted == False).update(
        {"is_deleted": True, "deleted_at": datetime.now(timezone.utc), "status": "inactive"},
        synchronize_session=False,
    )
    _log(db, admin, "empty_store", "product", "all", meta={"count": count})
    db.commit()
    return {"message": "Store emptied (soft-delete)", "deleted": count}


@router.post("/admin/bulk-archive", dependencies=[Depends(require_admin)])
def bulk_archive(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids   = payload.get("ids", [])
    count = db.query(Product).filter(Product.id.in_(ids), Product.is_deleted == False).update({"status": "archived"}, synchronize_session=False)
    db.commit()
    return {"updated": count}


@router.post("/admin/bulk-activate", dependencies=[Depends(require_admin)])
def bulk_activate(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids   = payload.get("ids", [])
    count = db.query(Product).filter(Product.id.in_(ids), Product.is_deleted == False).update({"status": "active"}, synchronize_session=False)
    db.commit()
    return {"updated": count}


@router.post("/admin/bulk-deactivate", dependencies=[Depends(require_admin)])
def bulk_deactivate(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids   = payload.get("ids", [])
    count = db.query(Product).filter(Product.id.in_(ids), Product.is_deleted == False).update({"status": "inactive"}, synchronize_session=False)
    db.commit()
    return {"updated": count}


@router.post("/admin/bulk-discount", dependencies=[Depends(require_admin)])
def bulk_discount(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids = payload.get("ids", [])
    pct = float(payload.get("discount_percent", 0))
    if not 0 < pct < 100:
        raise HTTPException(400, "discount_percent must be between 0 and 100")
    products = db.query(Product).filter(Product.id.in_(ids), Product.is_deleted == False).all()
    for p in products:
        p.compare_price = p.price
        p.price         = round(p.price * (1 - pct / 100), 2)
    db.commit()
    return {"updated": len(products)}


@router.post("/admin/bulk-restore-price", dependencies=[Depends(require_admin)])
def bulk_restore_price(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Restores original prices by swapping compare_price back."""
    ids      = payload.get("ids", [])
    products = db.query(Product).filter(Product.id.in_(ids), Product.compare_price.isnot(None)).all()
    for p in products:
        p.price         = p.compare_price
        p.compare_price = None
    db.commit()
    return {"updated": len(products)}


@router.post("/admin/bulk-category", dependencies=[Depends(require_admin)])
def bulk_category(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids           = payload.get("ids", [])
    category      = payload.get("category")
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
    ids      = payload.get("ids", [])
    store    = payload.get("store")
    store_id = payload.get("store_id")
    if not store and not store_id:
        raise HTTPException(400, "store or store_id is required")
    products = db.query(Product).filter(Product.id.in_(ids)).all()
    for p in products:
        if store:
            p.store = store
        if store_id:
            p.store_id = store_id
    db.commit()
    return {"updated": len(products)}


# ─────────────────────────────────────────────
# ADMIN: BULK UPLOAD (CSV)
# ─────────────────────────────────────────────

@router.post("/admin/bulk-upload", dependencies=[Depends(require_admin)])
async def bulk_upload_products(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """
    CSV columns:
    title, short_description, description, main_category, category, categories (JSON array),
    price, compare_price, rating, rating_number, brand, store, parent_asin, sku,
    stock, in_stock, features (JSON array), details (JSON object), image_urls (comma-separated)
    """
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "File must be .csv format")

    # Size check: 10MB max for CSV
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > 10 * 1024 * 1024:
        raise HTTPException(400, "CSV file must not exceed 10MB")

    upload_record = BulkUpload(
        filename=file.filename,
        uploaded_by=admin.id,
        status=BulkUploadStatus.processing,
    )
    db.add(upload_record)
    db.commit()
    db.refresh(upload_record)

    try:
        contents  = await file.read()
        # Handle BOM (Excel CSV exports)
        text_data = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text_data = contents.decode("latin-1")
        except Exception:
            upload_record.status = BulkUploadStatus.failed
            upload_record.errors = [{"row": 0, "error": "Cannot decode file. Use UTF-8 encoding."}]
            db.commit()
            raise HTTPException(400, "Cannot decode CSV file. Please use UTF-8 encoding.")

    csv_reader = csv.DictReader(io.StringIO(text_data))

    # Validate headers
    rows = list(csv_reader)
    if not rows:
        upload_record.status = BulkUploadStatus.failed
        upload_record.errors = [{"row": 0, "error": "CSV file is empty"}]
        db.commit()
        raise HTTPException(400, "CSV file is empty")

    required_headers = {"title", "price"}
    actual_headers   = set(rows[0].keys())
    missing_headers  = required_headers - actual_headers
    if missing_headers:
        upload_record.status = BulkUploadStatus.failed
        upload_record.errors = [{"row": 0, "error": f"Missing required columns: {', '.join(missing_headers)}"}]
        db.commit()
        raise HTTPException(400, f"CSV missing required columns: {', '.join(missing_headers)}")

    upload_record.total_rows = len(rows)
    db.commit()

    successful = 0
    failed     = 0
    errors     = []

    # JSON helper — defined once, outside loop
    def safe_json(val, fallback):
        """Parse a JSON string safely; return fallback on any failure."""
        if not val or (isinstance(val, str) and not val.strip()):
            return fallback
        try:
            result = json.loads(val)
            if fallback is not None and type(result) is not type(fallback):
                return fallback
            return result
        except (json.JSONDecodeError, TypeError, ValueError):
            return fallback

    for idx, row in enumerate(rows, 1):
        try:
            # Trim all string values
            row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

            title = row.get("title", "")
            if not title:
                raise ValueError("title is required")

            # Price
            try:
                price = float(row.get("price", 0) or 0)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid price: '{row.get('price')}'")
            if price < 0:
                raise ValueError("price cannot be negative")

            # Parse all fields first (needed for both insert and upsert)
            parent_asin = (row.get("parent_asin") or "").strip()

            # JSON fields
            categories = safe_json(row.get("categories"), [])
            features   = safe_json(row.get("features"),   [])
            details    = safe_json(row.get("details"), {})
            specs      = safe_json(row.get("specs"),   {})
            if isinstance(specs, dict) and specs:
                details = {**specs, **details}

            # Numeric fields
            stock               = int(float(row.get("stock", 10)               or 10))
            sales               = int(float(row.get("sales", 0)                or 0))
            rating              = float(row.get("rating", 0)                   or 0)
            rating_number       = int(float(row.get("rating_number", 0)        or 0))
            low_stock_threshold = int(float(row.get("low_stock_threshold", 10) or 10))

            compare_price_raw = row.get("compare_price", "")
            compare_price     = float(compare_price_raw) if compare_price_raw else None

            # CSV uses column name "matched_category", not "category"
            category = (
                row.get("category")
                or row.get("matched_category")
                or (categories[0] if isinstance(categories, list) and categories else "")
                or ""
            )

            # Status — validate against allowed values
            valid_statuses = {"active", "inactive", "draft", "archived", "discontinued"}
            status = (row.get("status") or "active").strip().lower()
            if status not in valid_statuses:
                status = "active"

            # UPSERT: if parent_asin already exists in DB, update instead of failing
            existing = (
                db.query(Product).filter(Product.parent_asin == parent_asin).first()
                if parent_asin else None
            )

            if existing and not existing.is_deleted:
                # Update the existing product with fresh data from CSV
                existing.title               = title[:500]
                existing.short_description   = (row.get("short_description") or title)[:500]
                existing.description         = row.get("description") or ""
                existing.main_category       = row.get("main_category") or ""
                existing.category            = category
                existing.categories          = categories
                existing.price               = price
                existing.compare_price       = compare_price
                existing.rating              = rating
                existing.rating_number       = rating_number
                existing.sales               = sales
                existing.brand               = row.get("brand") or ""
                existing.sku                 = row.get("sku") or existing.sku
                existing.features            = features
                existing.details             = details
                existing.store               = row.get("store") or existing.store
                existing.stock               = stock
                existing.in_stock            = stock > 0
                existing.status              = status
                existing.low_stock_threshold = low_stock_threshold
                product = existing
                # Replace images if new ones provided
                image_urls = [u.strip() for u in (row.get("image_urls") or "").split(",") if u.strip()]
                if image_urls:
                    for img in list(product.images):
                        db.delete(img)
                    db.flush()
                    for pos, url in enumerate(image_urls[:10]):
                        db.add(ProductImage(product_id=product.id, image_url=url, position=pos, is_primary=(pos == 0)))
            else:
                # Insert new product
                product = Product(
                    title               = title[:500],
                    short_description   = (row.get("short_description") or title)[:500],
                    description         = row.get("description") or "",
                    main_category       = row.get("main_category") or "",
                    category            = category,
                    categories          = categories,
                    price               = price,
                    compare_price       = compare_price,
                    rating              = rating,
                    rating_number       = rating_number,
                    sales               = sales,
                    brand               = row.get("brand") or "",
                    sku                 = row.get("sku") or None,
                    features            = features,
                    details             = details,
                    store               = row.get("store") or "",
                    parent_asin         = parent_asin or None,
                    stock               = stock,
                    in_stock            = stock > 0,
                    status              = status,
                    is_deleted          = False,
                    low_stock_threshold = low_stock_threshold,
                )
                db.add(product)
                db.flush()
                # Add images
                image_urls = [u.strip() for u in (row.get("image_urls") or "").split(",") if u.strip()]
                for pos, url in enumerate(image_urls[:10]):
                    db.add(ProductImage(product_id=product.id, image_url=url, position=pos, is_primary=(pos == 0)))

            db.commit()
            successful += 1

        except Exception as e:
            db.rollback()
            failed += 1
            errors.append({"row": idx, "title": row.get("title", ""), "error": str(e)})
            # FIX: use merge (not add) to safely re-attach after rollback
            upload_record = db.merge(upload_record)

    upload_record.successful_rows = successful
    upload_record.failed_rows     = failed
    upload_record.errors          = errors[:200]  # cap stored errors
    upload_record.status = (
        BulkUploadStatus.completed if failed == 0 else
        BulkUploadStatus.partial   if successful > 0 else
        BulkUploadStatus.failed
    )
    upload_record.completed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "upload_id":  str(upload_record.id),
        "total":      len(rows),
        "successful": successful,
        "failed":     failed,
        "status":     upload_record.status,
        "errors":     errors[:20],  # return first 20 in response
    }


@router.get("/admin/bulk-uploads", dependencies=[Depends(require_admin)])
def list_bulk_uploads(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    total   = db.query(BulkUpload).count()
    uploads = db.query(BulkUpload).order_by(BulkUpload.started_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total": total,
        "page":  page,
        "results": [
            {
                "id":              str(u.id),
                "filename":        u.filename,
                "status":          u.status,
                "total_rows":      u.total_rows,
                "successful_rows": u.successful_rows,
                "failed_rows":     u.failed_rows,
                "errors":          u.errors,
                "started_at":      u.started_at,
                "completed_at":    u.completed_at,
            }
            for u in uploads
        ],
    }


# ─────────────────────────────────────────────
# ADMIN: IMPORT / VALIDATE / PREVIEW / EXPORT
# ─────────────────────────────────────────────

@router.post("/admin/import-validate", dependencies=[Depends(require_admin)])
async def import_validate(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "File must be CSV")
    contents  = await file.read()
    text_data = contents.decode("utf-8-sig", errors="replace")
    reader    = csv.DictReader(io.StringIO(text_data))
    rows      = list(reader)
    errors, warnings = [], []

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
        if asin and db.query(Product).filter(Product.parent_asin == asin).first():
            warnings.append({"row": idx, "field": "parent_asin", "warning": f"Duplicate ASIN: {asin}"})

    return {
        "total_rows": len(rows),
        "errors":     errors,
        "warnings":   warnings,
        "valid":      len(errors) == 0,
    }


@router.post("/admin/import-preview", dependencies=[Depends(require_admin)])
async def import_preview(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "File must be CSV")
    contents  = await file.read()
    text_data = contents.decode("utf-8-sig", errors="replace")
    reader    = csv.DictReader(io.StringIO(text_data))
    rows      = list(reader)
    return {
        "total_rows": len(rows),
        "columns":    list(rows[0].keys()) if rows else [],
        "preview": [
            {
                "title":        row.get("title", ""),
                "price":        row.get("price", ""),
                "category":     row.get("main_category", ""),
                "stock":        row.get("stock", ""),
                "parent_asin":  row.get("parent_asin", ""),
                "store":        row.get("store", ""),
                "brand":        row.get("brand", ""),
                "image_count":  len([u for u in (row.get("image_urls", "") or "").split(",") if u.strip()]),
            }
            for row in rows[:10]
        ],
    }


@router.get("/admin/export", dependencies=[Depends(require_admin)])
def export_products(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    store: Optional[str] = None,
    category: Optional[str] = None,
    include_deleted: bool = False,
):
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
        "status", "is_deleted", "parent_asin", "created_at",
    ])
    for p in products:
        writer.writerow([
            str(p.id), p.title, p.sku, p.brand, p.store, p.category, p.main_category,
            p.price, p.compare_price, p.stock, p.rating, p.rating_number, p.sales,
            p.status, p.is_deleted, p.parent_asin, p.created_at,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products_export.csv"},
    )


# ─────────────────────────────────────────────
# VARIANT ROUTES  (before /{product_id})
# ─────────────────────────────────────────────

@router.patch("/variants/bulk", dependencies=[Depends(require_admin)])
def bulk_update_variants(payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    ids     = payload.get("ids", [])
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


@router.patch("/variants/{variant_id}/inventory", dependencies=[Depends(require_admin)])
def update_variant_inventory(variant_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    variant = db.query(ProductVariant).filter(ProductVariant.id == variant_id).first()
    if not variant:
        raise HTTPException(404, "Variant not found")
    new_stock = int(payload.get("stock", variant.stock))
    db.add(InventoryAdjustment(
        product_id=variant.product_id,
        variant_id=variant.id,
        adjustment_type=payload.get("type", "manual"),
        quantity_before=variant.stock,
        quantity_change=new_stock - variant.stock,
        quantity_after=new_stock,
        note=payload.get("note"),
        reference=payload.get("reference"),
        admin_id=admin.id,
    ))
    variant.stock    = new_stock
    variant.in_stock = new_stock > 0
    db.commit()
    return {"message": "Variant inventory updated", "stock": new_stock}


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
        product_id    = original.product_id,
        title         = f"{original.title} (Copy)",
        sku           = f"{original.sku}-copy" if original.sku else None,
        attributes    = original.attributes,
        price         = original.price,
        compare_price = original.compare_price,
        stock         = original.stock,
        in_stock      = original.in_stock,
        image_url     = original.image_url,
        is_active     = False,
    )
    db.add(new_v)
    _log(db, admin, "duplicate", "variant", new_v.id, meta={"source_id": str(variant_id)})
    db.commit()
    db.refresh(new_v)
    return {"id": str(new_v.id), "message": "Variant duplicated"}


# ─────────────────────────────────────────────
# IMAGE ROUTES  (before /{product_id})
# ─────────────────────────────────────────────

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
    db.query(ProductImage).filter(ProductImage.product_id == image.product_id).update({"is_primary": False})
    image.is_primary = True
    image.position   = 0
    db.commit()
    return {"message": "Primary image set"}


@router.delete("/images/{image_id}", dependencies=[Depends(require_admin)])
def delete_image(image_id: str, db: Session = Depends(get_db)):
    image = db.query(ProductImage).filter(ProductImage.id == image_id).first()
    if not image:
        raise HTTPException(404, "Image not found")
    # Don't allow deleting the only image
    count = db.query(ProductImage).filter(ProductImage.product_id == image.product_id).count()
    if count <= 1:
        raise HTTPException(400, "Cannot delete the only image. Add another image first.")
    # If deleting primary, promote next one
    if image.is_primary:
        next_img = db.query(ProductImage).filter(
            ProductImage.product_id == image.product_id,
            ProductImage.id != image_id,
        ).order_by(ProductImage.position).first()
        if next_img:
            next_img.is_primary = True
    db.delete(image)
    db.commit()
    return {"message": "Image deleted"}


# ─────────────────────────────────────────────
# PUBLIC: GET SINGLE PRODUCT  (wildcard — LAST)
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
# ADMIN: PRODUCT LIFECYCLE  (wildcard — after all statics)
# ─────────────────────────────────────────────

@router.delete("/{product_id}", dependencies=[Depends(require_admin)])
def soft_delete_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before          = _product_snapshot(product)
    product.is_deleted = True
    product.deleted_at = datetime.now(timezone.utc)
    product.status     = "inactive"
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
        title               = f"{original.title} (Copy)",
        short_description   = original.short_description,
        description         = original.description,
        sku                 = f"{original.sku}-copy" if original.sku else None,
        brand               = original.brand,
        price               = original.price,
        compare_price       = original.compare_price,
        rating              = 0,
        rating_number       = 0,
        sales               = 0,
        category            = original.category,
        main_category       = original.main_category,
        categories          = original.categories,
        details             = original.details,
        features            = original.features,
        stock               = original.stock,
        in_stock            = original.in_stock,
        low_stock_threshold = original.low_stock_threshold,
        store               = original.store,
        store_id            = original.store_id,
        status              = "draft",
        is_deleted          = False,
    )
    db.add(new_product)
    db.flush()
    for img in original.images:
        db.add(ProductImage(product_id=new_product.id, image_url=img.image_url, position=img.position, is_primary=img.is_primary))
    _log(db, admin, "duplicate", "product", new_product.id, meta={"source_id": str(product_id)})
    db.commit()
    db.refresh(new_product)
    return {"id": str(new_product.id), "message": "Product duplicated as draft"}


@router.post("/{product_id}/archive", dependencies=[Depends(require_admin)])
def archive_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before          = _product_snapshot(product)
    product.status  = "archived"
    _log(db, admin, "archive", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    return {"message": "Product archived"}


@router.post("/{product_id}/restore", dependencies=[Depends(require_admin)])
def restore_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before             = _product_snapshot(product)
    product.is_deleted = False
    product.deleted_at = None
    product.status     = "active"
    _log(db, admin, "restore", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    return {"message": "Product restored and set to active"}


@router.post("/{product_id}/publish", dependencies=[Depends(require_admin)])
def publish_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    if not product.price or product.price <= 0:
        raise HTTPException(400, "Cannot publish product with no price")
    before         = _product_snapshot(product)
    product.status = "active"
    _log(db, admin, "publish", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    return {"message": "Product published"}


@router.post("/{product_id}/draft", dependencies=[Depends(require_admin)])
def draft_product(product_id: str, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    before         = _product_snapshot(product)
    product.status = "draft"
    _log(db, admin, "draft", "product", product_id, before=before, after=_product_snapshot(product))
    db.commit()
    return {"message": "Product set to draft"}


@router.get("/{product_id}/variants")
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
            "id":           str(v.id),
            "title":        v.title,
            "sku":          v.sku,
            "attributes":   v.attributes,
            "price":        v.price,
            "compare_price": v.compare_price,
            "stock":        v.stock,
            "in_stock":     v.stock > 0,
            "image_url":    v.image_url,
            "is_active":    v.is_active,
            "created_at":   v.created_at,
        }
        for v in variants
    ]


@router.post("/{product_id}/variants", dependencies=[Depends(require_admin)])
def create_variant(product_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    stock   = int(payload.get("stock", 0))
    variant = ProductVariant(
        product_id    = product_id,
        title         = payload.get("title", ""),
        sku           = payload.get("sku"),
        attributes    = payload.get("attributes", {}),
        price         = float(payload.get("price", product.price)),
        compare_price = payload.get("compare_price"),
        stock         = stock,
        in_stock      = stock > 0,
        image_url     = payload.get("image_url"),
        is_active     = payload.get("is_active", True),
    )
    db.add(variant)
    _log(db, admin, "create", "variant", variant.id, after={"title": variant.title, "price": variant.price})
    db.commit()
    db.refresh(variant)
    return {"id": str(variant.id), "message": "Variant created"}


@router.post("/{product_id}/images/bulk", dependencies=[Depends(require_admin)])
def bulk_add_images(product_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")
    urls = payload.get("urls", [])
    if not urls:
        raise HTTPException(400, "urls required")
    max_pos = max((img.position for img in product.images), default=-1)
    has_primary = any(img.is_primary for img in product.images)
    for i, url in enumerate(urls):
        db.add(ProductImage(
            product_id = product_id,
            image_url  = url,
            position   = max_pos + i + 1,
            is_primary = (i == 0 and not has_primary),
        ))
    db.commit()
    return {"added": len(urls)}


@router.patch("/{product_id}/inventory", dependencies=[Depends(require_admin)])
def update_product_inventory(product_id: str, payload: dict, db: Session = Depends(get_db), admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id, Product.is_deleted == False).first()
    if not product:
        raise HTTPException(404, "Product not found")
    new_stock = int(payload.get("stock", product.stock))
    if new_stock < 0:
        raise HTTPException(400, "stock cannot be negative")
    db.add(InventoryAdjustment(
        product_id      = product.id,
        adjustment_type = payload.get("type", "manual"),
        quantity_before = product.stock,
        quantity_change = new_stock - product.stock,
        quantity_after  = new_stock,
        note            = payload.get("note"),
        reference       = payload.get("reference"),
        admin_id        = admin.id,
    ))
    product.stock    = new_stock
    product.in_stock = new_stock > 0
    db.commit()
    return {"message": "Inventory updated", "stock": new_stock}