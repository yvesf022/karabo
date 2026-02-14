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
# ADMIN: BULK UPLOAD FROM CSV 🚀 (FIXED VERSION)
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

                # Prevent duplicates
                if parent_asin:
                    existing = (
                        db.query(Product)
                        .filter(Product.parent_asin == parent_asin)
                        .first()
                    )
                    if existing:
                        raise ValueError(
                            f"Duplicate parent_asin: {parent_asin}"
                        )

                # Parse JSON safely
                categories = json.loads(row.get("categories", "[]") or "[]")
                features = json.loads(row.get("features", "[]") or "[]")
                details = json.loads(row.get("details", "{}") or "{}")

                # Parse numeric safely
                price = float(row.get("price", 0) or 0)
                rating = float(row.get("rating", 0) or 0)
                rating_number = int(row.get("rating_number", 0) or 0)
                stock = int(row.get("stock", 10) or 10)

                # Boolean parsing
                in_stock = (
                    str(row.get("in_stock", "true")).lower() == "true"
                )

                product = Product(
                    title=title,
                    short_description=row.get(
                        "short_description", title
                    )[:200],
                    description=row.get("description", ""),
                    main_category=row.get("main_category", ""),
                    category=categories[0]
                    if categories
                    else row.get("main_category", ""),
                    categories=categories,
                    price=price,
                    compare_price=float(
                        row.get("compare_price", 0) or 0
                    ),
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

                # 🔥 FIX: Read image_urls column correctly
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
