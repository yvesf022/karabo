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

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB (covers products + proofs)

ALLOWED_FOLDERS = {
    "avatars",
    "products",
    "payments",
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
    - Returns secure URL (stored in DB)
    """

    # -------------------------
    # Validate folder
    # -------------------------
    if folder not in ALLOWED_FOLDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload destination",
        )

    # -------------------------
    # Validate file
    # -------------------------
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file uploaded",
        )

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type",
        )

    # -------------------------
    # Validate file size (stream-safe)
    # -------------------------
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
            detail="File size exceeds allowed limit (15MB)",
        )

    # -------------------------
    # Generate Cloudinary public_id
    # -------------------------
    public_id = f"{folder}_{owner_id}_{uuid.uuid4().hex}"

    # -------------------------
    # Upload to Cloudinary
    # -------------------------
    try:
        if file.content_type in IMAGE_TYPES:
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
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file",
        )

    if not url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload returned no URL",
        )

    return url
