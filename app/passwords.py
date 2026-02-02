from passlib.context import CryptContext
from fastapi import HTTPException

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

BCRYPT_MAX_BYTES = 72


def _validate_password_length(password: str):
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Password too long (max 72 bytes)",
        )


def hash_password(password: str) -> str:
    _validate_password_length(password)
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    _validate_password_length(plain)
    return pwd_context.verify(plain, hashed)
