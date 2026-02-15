from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    """
    Keep-alive endpoint for Render free tier.
    Called every 2 minutes to prevent shutdown.
    """
    return {
        "status": "healthy",
        "message": "Server is awake",
        "timestamp": "2025-01-01T00:00:00Z"
    }


@router.get("/ping")
def ping():
    """
    Simple ping endpoint
    """
    return {"ping": "pong"}