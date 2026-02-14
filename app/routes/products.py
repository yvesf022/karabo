from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
)
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
import csv
import io
import json
from datetime import datetime

from app.database import get_db
from app.models import (
    Product,
    ProductImage,
    ProductStatus,
    BulkUpload,
    BulkUploadStatus,
)
from app.dependencies import require_admin
from app.uploads.service import handle_upload

router = APIRouter(prefix="/products", tags=["products"])


# =====================================================
# PUBLIC: LIST PRODUCTS
# =====================================================
@router.get("")
def list_products(
    db: Session = Depends(get_db),
    search_query: Optional[str] = None,
    category: Optional[str] = None,
    main_category: Optional[str] = None,
    brand: Optional[str] = None,
    store: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock: Optional[bool] = None,
    min_rating: Optional[float] = None,
    sort: Optional[str] = "featured",
    page: int = 1,
    per_page: int = 20,
):
    page = max(page, 1)
    per_page = min(max(per_page, 1), 100)

    query = db.query(Product).filter(Product.status == ProductStatus.active)

    if search_query:
        query = query.filter(
            func.to_tsvector("english", Product.title).match(search_query)
            | func.to_tsvector("english", Product.short_description).match(search_query)
        )

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

    query = query.order_by(Product.created_at.desc())

    products = (
        query.offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return [
        {
            "id": str(p.id),
            "title": p.title,
            "short_description": p.short_description,
            "price": p.price,
            "brand": p.brand,
            "store": p.store,
            "rating": p.rating,
            "rating_number": p.rating_number,
            "sales": p.sales,
            "category": p.category,
            "main_category": p.main_category,
            "stock": p.stock,
            "main_image": p.images[0].image_url if p.images else None,
            "images": [img.image_url for img in p.images],
            "created_at": p.created_at,
        }
        for p in products
    ]


# =====================================================
# ADMIN: BULK UPLOAD FROM CSV 🚀
# =====================================================
@router.post("/admin/bulk-upload", dependencies=[Depends(require_admin)])
async def bulk_upload_products(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):

    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be CSV format")

    upload_record = BulkUpload(
        filename=file.filename,
        uploaded_by=admin.id,
        status=BulkUploadStatus.processing,
    )
    db.add(upload_record)
    db.commit()
    db.refresh(upload_record)

    try:
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
                    existing = (
                        db.query(Product)
                        .filter(Product.parent_asin == parent_asin)
                        .first()
                    )
                    if existing:
                        raise ValueError(f"Duplicate parent_asin: {parent_asin}")

                categories = json.loads(row.get("categories", "[]") or "[]")
                features = json.loads(row.get("features", "[]") or "[]")
                details = json.loads(row.get("details", "{}") or "{}")

                price = float(row.get("price", 0) or 0)
                compare_price = float(row.get("compare_price", 0) or 0)
                rating = float(row.get("rating", 0) or 0)
                rating_number = int(row.get("rating_number", 0) or 0)
                stock = int(row.get("stock", 10) or 10)
                in_stock = str(row.get("in_stock", "true")).lower() == "true"

                product = Product(
                    title=title,
                    short_description=row.get("short_description", title)[:200],
                    description=row.get("description", ""),
                    main_category=row.get("main_category", ""),
                    category=categories[0] if categories else row.get("main_category", ""),
                    categories=categories,
                    price=price,
                    compare_price=compare_price,
                    rating=rating,
                    rating_number=rating_number,
                    features=features,
                    details=details,
                    store=row.get("store", ""),
                    parent_asin=parent_asin,
                    stock=stock,
                    in_stock=in_stock,
                    status=ProductStatus.active,
                )

                db.add(product)
                db.flush()

                image_urls_raw = row.get("image_urls", "")
                image_urls = [
                    url.strip()
                    for url in image_urls_raw.split(",")
                    if url.strip()
                ]

                for position, url in enumerate(image_urls[:10]):
                    db.add(
                        ProductImage(
                            product_id=product.id,
                            image_url=url,
                            position=position,
                        )
                    )

                successful += 1

            except Exception as e:
                failed += 1
                errors.append(
                    {
                        "row": idx,
                        "error": str(e),
                        "title": row.get("title", "Unknown"),
                    }
                )

        upload_record.successful_rows = successful
        upload_record.failed_rows = failed
        upload_record.errors = errors[:100]
        upload_record.summary = {
            "total": len(rows),
            "successful": successful,
            "failed": failed,
            "success_rate": f"{(successful/len(rows)*100):.1f}%"
            if rows
            else "0%",
        }

        upload_record.status = (
            BulkUploadStatus.completed
            if failed == 0
            else BulkUploadStatus.partial
            if successful > 0
            else BulkUploadStatus.failed
        )

        upload_record.completed_at = datetime.utcnow()
        db.commit()

        return {
            "upload_id": str(upload_record.id),
            "total_rows": len(rows),
            "successful": successful,
            "failed": failed,
            "status": upload_record.status,
            "errors": errors[:10],
        }

    except Exception as e:
        upload_record.status = BulkUploadStatus.failed
        upload_record.errors = [{"error": str(e)}]
        db.commit()
        raise HTTPException(500, f"Upload failed: {str(e)}")


# =====================================================
# ADMIN: LIST BULK UPLOADS
# =====================================================
@router.get("/admin/bulk-uploads", dependencies=[Depends(require_admin)])
def list_bulk_uploads(db: Session = Depends(get_db)):
    uploads = (
        db.query(BulkUpload)
        .order_by(BulkUpload.started_at.desc())
        .limit(50)
        .all()
    )

    return [
        {
            "id": str(u.id),
            "filename": u.filename,
            "status": u.status,
            "total_rows": u.total_rows,
            "successful_rows": u.successful_rows,
            "failed_rows": u.failed_rows,
            "summary": u.summary,
            "started_at": u.started_at,
            "completed_at": u.completed_at,
        }
        for u in uploads
    ]
