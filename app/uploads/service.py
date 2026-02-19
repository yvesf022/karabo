import uuid
from fastapi import UploadFile, HTTPException, status

from app.cloudinary_client import upload_image, upload_file

# ======================================================
# GLOBAL UPLOAD RULES (SINGLE SOURCE OF TRUTH)
# ======================================================

IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
}

FILE_TYPES = {
    "application/pdf",
}

ALLOWED_TYPES = IMAGE_TYPES | FILE_TYPES

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB

# ✅ FIXED: "payment_proofs" was missing — caused 400 on resubmit-proof endpoint
ALLOWED_FOLDERS = {
    "avatars",
    "products",
    "payments",
    "payment_proofs",
}

# ======================================================
# CENTRAL UPLOAD HANDLER
# ======================================================

def handle_upload(
    file: UploadFile,
    folder: str,
    owner_id: str,
) -> str:
    """
    Centralized upload handler.
    - Validates file type & size
    - Enforces allowed folders
    - Uploads to Cloudinary
    - Returns secure URL
    """

    if folder not in ALLOWED_FOLDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid upload destination: '{folder}'",
        )

    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file uploaded",
        )

    content_type = (file.content_type or "").lower().strip()

    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: '{content_type}'. Allowed: images (JPEG, PNG, WebP, GIF) and PDF.",
        )

    # Stream-safe size check
    try:
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read uploaded file",
        )

    if size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size {round(size / 1024 / 1024, 1)}MB exceeds 15MB limit",
        )

    # Unique public_id per upload — prevents Cloudinary cache collisions
    public_id = f"{folder}_{owner_id}_{uuid.uuid4().hex}"

    try:
        if content_type in IMAGE_TYPES:
            url = upload_image(
                file=file.file,
                folder=folder,
                public_id=public_id,
                allowed_formats=["jpg", "jpeg", "png", "webp", "gif"],
            )
        else:
            url = upload_file(
                file=file.file,
                folder=folder,
                public_id=public_id,
            )
    except HTTPException:
        raise  # re-raise known HTTP exceptions as-is
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}",
        )

    if not url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload succeeded but returned no URL",
        )

    return url