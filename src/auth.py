"""
auth.py — JWT authentication helpers and FastAPI dependency for JUDGE.

Provides:
    hash_password(plain)           -> str   (bcrypt hash)
    verify_password(plain, hashed) -> bool  (bcrypt verify)
    create_access_token(user_id)   -> str   (HS256 JWT)
    get_current_user(token)        -> str   (FastAPI Depends — returns user_id)

Environment variables read:
    JWT_SECRET      — signing key (required)
    JWT_EXPIRY_HOURS — token lifetime in hours (default: 24)
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

# ── Passlib bcrypt context ────────────────────────────────────────────────────
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── OAuth2 bearer scheme (reads Authorization: Bearer <token>) ────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# ── JWT configuration ─────────────────────────────────────────────────────────
_ALGORITHM = "HS256"


def _get_jwt_secret() -> str:
    """Read JWT_SECRET from environment. Raises at call-time if unset."""
    secret = os.getenv("JWT_SECRET", "")
    if not secret or secret.startswith("<"):
        raise RuntimeError(
            "JWT_SECRET is not configured. Set it in your .env file."
        )
    return secret


def _get_expiry_hours() -> int:
    try:
        return int(os.getenv("JWT_EXPIRY_HOURS", "24"))
    except ValueError:
        return 24


# ── Public API ────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    return _pwd_context.verify(plain, hashed)


def create_access_token(user_id: str) -> str:
    """Create a signed HS256 JWT encoding *user_id* as the subject.

    The token expires after JWT_EXPIRY_HOURS hours (default 24).
    """
    expiry = datetime.now(timezone.utc) + timedelta(hours=_get_expiry_hours())
    payload = {
        "sub": user_id,
        "exp": expiry,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """FastAPI dependency — decode and validate the bearer token.

    Returns the user_id (JWT 'sub' claim) on success.
    Raises HTTP 401 on missing, expired, or invalid tokens.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[_ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if not user_id:
            raise credentials_exception
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise credentials_exception
