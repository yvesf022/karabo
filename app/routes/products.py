from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    status,
    BackgroundTasks,
)
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
import csv
import io
import json
from datetime import datetime

from app.database import get_db
from app.models import Product, ProductImage, ProductStatus, BulkUpload, BulkUploadStatus
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
            | func.to_tsvector(
                "english", Product.short_description
            ).match(search_query)
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
        query = query.filter(
            Product.stock > 0 if in_stock else Product.stock <= 0
        )
    if min_rating is not None:
        query = query.filter(Product.rating >= min_rating)

    if sort == "price_low":
        query = query.order_by(Product.price.asc())
    elif sort == "price_high":
        query = query.order_by(Product.price.desc())
    elif sort == "rating":
        query = query.order_by(Product.rating.desc())
    elif sort == "best_sellers":
        query = query.order_by(Product.sales.desc())
    else:
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
# PUBLIC: GET SINGLE PRODUCT
# =====================================================
@router.get("/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            Product.status == ProductStatus.active,
        )
        .first()
    )

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return {
        "id": str(product.id),
        "title": product.title,
        "short_description": product.short_description,
        "description": product.description,
        "price": product.price,
        "compare_price": product.compare_price,
        "brand": product.brand,
        "store": product.store,
        "parent_asin": product.parent_asin,
        "rating": product.rating,
        "rating_number": product.rating_number,
        "sales": product.sales,
        "category": product.category,
        "main_category": product.main_category,
        "categories": product.categories,
        "features": product.features,
        "details": product.details,
        "stock": product.stock,
        "in_stock": product.stock > 0,
        "main_image": product.images[0].image_url if product.images else None,
        "images": [img.image_url for img in product.images],
        "created_at": product.created_at,
    }


# =====================================================
# ADMIN: CREATE PRODUCT
# =====================================================
@router.post("", dependencies=[Depends(require_admin)])
def create_product(payload: dict, db: Session = Depends(get_db)):
    product = Product(
        title=payload["title"],
        short_description=payload.get("short_description"),
        description=payload.get("description"),
        sku=payload.get("sku"),
        brand=payload.get("brand"),
        store=payload.get("store"),
        parent_asin=payload.get("parent_asin"),
        price=payload["price"],
        compare_price=payload.get("compare_price"),
        category=payload.get("category"),
        main_category=payload.get("main_category"),
        categories=payload.get("categories"),
        features=payload.get("features"),
        details=payload.get("details"),
        stock=payload.get("stock", 0),
        rating=payload.get("rating"),
        rating_number=payload.get("rating_number", 0),
        status=ProductStatus.active,
    )

    product.in_stock = product.stock > 0

    db.add(product)
    db.commit()
    db.refresh(product)

    return {"id": str(product.id), "title": product.title}


# =====================================================
# ADMIN: UPDATE PRODUCT
# =====================================================
@router.patch("/admin/{product_id}", dependencies=[Depends(require_admin)])
def update_product(product_id: str, payload: dict, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")

    # Update fields
    if "title" in payload:
        product.title = payload["title"]
    if "short_description" in payload:
        product.short_description = payload["short_description"]
    if "description" in payload:
        product.description = payload["description"]
    if "price" in payload:
        product.price = payload["price"]
    if "compare_price" in payload:
        product.compare_price = payload["compare_price"]
    if "category" in payload:
        product.category = payload["category"]
    if "brand" in payload:
        product.brand = payload["brand"]
    if "stock" in payload:
        product.stock = payload["stock"]
        product.in_stock = product.stock > 0

    db.commit()
    return {"message": "Product updated"}


# =====================================================
# ADMIN: BULK UPLOAD FROM CSV 🚀
# =====================================================
@router.post("/admin/bulk-upload", dependencies=[Depends(require_admin)])
async def bulk_upload_products(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    admin = Depends(require_admin),
):
    """
    Upload products in bulk from CSV file.
    Expected CSV columns: title, main_category, price, description, features, 
    images, store, categories, details, parent_asin, rating, rating_number
    """
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(400, "File must be CSV format")

    # Create upload record
    upload_record = BulkUpload(
        filename=file.filename,
        uploaded_by=admin.id,
        status=BulkUploadStatus.processing,
    )
    db.add(upload_record)
    db.commit()
    db.refresh(upload_record)

    try:
        # Read CSV
        contents = await file.read()
        csv_data = contents.decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_data))
        
        rows = list(csv_reader)
        upload_record.total_rows = len(rows)
        db.commit()

        successful = 0
        failed = 0
        errors = []

        for idx, row in enumerate(rows, 1):
            try:
                # Parse JSON fields
                features = json.loads(row.get('features', '[]')) if row.get('features') else []
                description = json.loads(row.get('description', '[]')) if row.get('description') else []
                images = json.loads(row.get('images', '[]')) if row.get('images') else []
                categories = json.loads(row.get('categories', '[]')) if row.get('categories') else []
                details = json.loads(row.get('details', '{}')) if row.get('details') else {}

                # Create description text from array
                description_text = "\n".join(description) if isinstance(description, list) else description

                # Check for duplicate by parent_asin or title
                parent_asin = row.get('parent_asin', '').strip()
                if parent_asin:
                    existing = db.query(Product).filter(Product.parent_asin == parent_asin).first()
                    if existing:
                        errors.append({
                            "row": idx,
                            "error": f"Duplicate parent_asin: {parent_asin}",
                            "title": row.get('title')
                        })
                        failed += 1
                        continue

                # Create product
                product = Product(
                    title=row['title'].strip(),
                    short_description=row.get('title', '').strip()[:200],  # Use title as short desc
                    description=description_text,
                    main_category=row.get('main_category', '').strip(),
                    category=categories[0] if categories else row.get('main_category', ''),
                    categories=categories,
                    price=float(row.get('price', 0)),
                    rating=float(row.get('average_rating', row.get('rating', 0))),
                    rating_number=int(row.get('rating_number', 0)),
                    features=features,
                    details=details,
                    store=row.get('store', '').strip(),
                    parent_asin=parent_asin,
                    stock=10,  # Default stock
                    in_stock=True,
                    status=ProductStatus.active,
                )

                db.add(product)
                db.flush()  # Get product ID

                # Add images
                for position, img_url in enumerate(images[:10]):  # Max 10 images
                    if img_url.strip():
                        image = ProductImage(
                            product_id=product.id,
                            image_url=img_url.strip(),
                            position=position,
                        )
                        db.add(image)

                successful += 1

            except Exception as e:
                failed += 1
                errors.append({
                    "row": idx,
                    "error": str(e),
                    "title": row.get('title', 'Unknown')
                })

        # Update upload record
        upload_record.successful_rows = successful
        upload_record.failed_rows = failed
        upload_record.errors = errors[:100]  # Store first 100 errors
        upload_record.summary = {
            "total": len(rows),
            "successful": successful,
            "failed": failed,
            "success_rate": f"{(successful/len(rows)*100):.1f}%" if len(rows) > 0 else "0%"
        }
        upload_record.status = (
            BulkUploadStatus.completed if failed == 0
            else BulkUploadStatus.partial if successful > 0
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
            "errors": errors[:10],  # Return first 10 errors
        }

    except Exception as e:
        upload_record.status = BulkUploadStatus.failed
        upload_record.errors = [{"error": str(e)}]
        db.commit()
        raise HTTPException(500, f"Upload failed: {str(e)}")


# =====================================================
# ADMIN: GET BULK UPLOAD STATUS
# =====================================================
@router.get("/admin/bulk-uploads/{upload_id}", dependencies=[Depends(require_admin)])
def get_bulk_upload_status(upload_id: str, db: Session = Depends(get_db)):
    upload = db.query(BulkUpload).filter(BulkUpload.id == upload_id).first()
    if not upload:
        raise HTTPException(404, "Upload not found")

    return {
        "id": str(upload.id),
        "filename": upload.filename,
        "status": upload.status,
        "total_rows": upload.total_rows,
        "successful_rows": upload.successful_rows,
        "failed_rows": upload.failed_rows,
        "errors": upload.errors,
        "summary": upload.summary,
        "started_at": upload.started_at,
        "completed_at": upload.completed_at,
    }


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


# =====================================================
# ADMIN: UPLOAD PRODUCT IMAGE
# =====================================================
@router.post(
    "/admin/{product_id}/images",
    dependencies=[Depends(require_admin)],
)
def upload_product_image(
    product_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    image_url = handle_upload(
        file=file,
        folder="products",
        owner_id=str(product.id),
    )

    position = (
        db.query(ProductImage)
        .filter(ProductImage.product_id == product.id)
        .count()
    )

    image = ProductImage(
        product_id=product.id,
        image_url=image_url,
        position=position,
    )

    db.add(image)
    db.commit()
    db.refresh(image)

    return {
        "url": image.image_url,
        "position": image.position,
    }


# =====================================================
# ADMIN: DELETE PRODUCT IMAGE
# =====================================================
@router.delete(
    "/admin/images/{image_id}",
    dependencies=[Depends(require_admin)],
)
def delete_product_image(image_id: str, db: Session = Depends(get_db)):
    image = (
        db.query(ProductImage)
        .filter(ProductImage.id == image_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    product_id = image.product_id
    db.delete(image)
    db.commit()

    images = (
        db.query(ProductImage)
        .filter(ProductImage.product_id == product_id)
        .order_by(ProductImage.position)
        .all()
    )

    for idx, img in enumerate(images):
        img.position = idx

    db.commit()

    return {"detail": "Image deleted"}


# =====================================================
# ADMIN: REORDER PRODUCT IMAGES
# =====================================================
@router.put(
    "/admin/{product_id}/images/reorder",
    dependencies=[Depends(require_admin)],
)
def reorder_product_images(
    product_id: str,
    image_ids: List[str],
    db: Session = Depends(get_db),
):
    images = (
        db.query(ProductImage)
        .filter(
            ProductImage.product_id == product_id,
            ProductImage.id.in_(image_ids),
        )
        .all()
    )

    if len(images) != len(image_ids):
        raise HTTPException(
            status_code=400,
            detail="Invalid image list",
        )

    image_map = {str(img.id): img for img in images}

    for position, image_id in enumerate(image_ids):
        image_map[image_id].position = position

    db.commit()

    return {"detail": "Images reordered"}


# =====================================================
# ADMIN: SET MAIN IMAGE
# =====================================================
@router.post(
    "/admin/images/{image_id}/set-main",
    dependencies=[Depends(require_admin)],
)
def set_main_image(image_id: str, db: Session = Depends(get_db)):
    image = (
        db.query(ProductImage)
        .filter(ProductImage.id == image_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    images = (
        db.query(ProductImage)
        .filter(ProductImage.product_id == image.product_id)
        .order_by(ProductImage.position)
        .all()
    )

    for img in images:
        img.position += 1

    image.position = 0
    db.commit()

    return {"detail": "Main image set"}