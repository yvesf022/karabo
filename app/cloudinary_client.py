import os
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url
from fastapi import HTTPException, status

# =====================================================
# CLOUDINARY CONFIGURATION (ENV-BASED ONLY)
# =====================================================

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

if not all(
    [CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]
):
    raise RuntimeError(
        "Cloudinary environment variables are not set. "
        "Please configure CLOUDINARY_CLOUD_NAME, "
        "CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET."
    )

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)

# =====================================================
# UPLOAD HELPERS
# =====================================================

def upload_image(
    file,
    folder: str,
    public_id: str | None = None,
    allowed_formats: list[str] | None = None,
):
    """
    Upload an image file to Cloudinary.
    Returns the ORIGINAL secure URL (stored in DB).
    """

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            public_id=public_id,
            resource_type="image",
            allowed_formats=allowed_formats,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload image to cloud storage.",
        )

    return result["secure_url"]


def upload_file(
    file,
    folder: str,
    public_id: str | None = None,
):
    """
    Upload a non-image file (e.g. PDF payment proof) to Cloudinary.
    """

    try:
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            public_id=public_id,
            resource_type="raw",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file to cloud storage.",
        )

    return result["secure_url"]

# =====================================================
# OPTIMIZED DELIVERY HELPERS (NO DB CHANGES)
# =====================================================

def optimize_image(
    original_url: str,
    width: int | None = None,
    height: int | None = None,
    crop: str = "fill",
):
    """
    Generate an optimized Cloudinary URL:
    - auto format (webp/avif)
    - auto quality
    - optional resize
    """

    if not original_url:
        return None

    try:
        public_id = original_url.split("/")[-1].split(".")[0]

        url, _ = cloudinary_url(
            public_id,
            fetch_format="auto",
            quality="auto",
            width=width,
            height=height,
            crop=crop if width or height else None,
            secure=True,
        )
        return url
    except Exception:
        return original_url


# =====================================================
# PRESET HELPERS (E-COMMERCE FRIENDLY)
# =====================================================

def product_thumbnail(url: str):
    """Small image for product listing"""
    return optimize_image(url, width=300, height=300)


def product_card(url: str):
    """Medium image for product cards"""
    return optimize_image(url, width=600, height=600)


def product_detail(url: str):
    """Large image for product detail page"""
    return optimize_image(url, width=1000, height=1000)


def avatar_image(url: str):
    """Optimized avatar"""
    return optimize_image(url, width=200, height=200)
