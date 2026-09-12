"""
auth_router.py — Authentication routes for JUDGE.

Routes:
    POST /auth/signup  — register a new user, return access token
    POST /auth/login   — verify credentials, return access token
    GET  /auth/me      — return user_id from valid bearer token (protected)
"""

import os
import sys
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.auth import hash_password, verify_password, create_access_token, get_current_user
from src.mongo_db import get_users_collection

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ── Request / Response models ─────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest) -> Dict[str, Any]:
    """Register a new user.

    - Rejects duplicate emails with 409.
    - Hashes password with bcrypt before storage.
    - Returns a signed JWT on success.
    """
    users = get_users_collection()

    # Check for existing account
    existing = await users.find_one({"email": body.email})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{body.email}' already exists.",
        )

    # Store user document
    user_doc = {
        "email": body.email,
        "hashed_password": hash_password(body.password),
    }
    result = await users.insert_one(user_doc)
    user_id = str(result.inserted_id)

    token = create_access_token(user_id)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> Dict[str, Any]:
    """Authenticate an existing user.

    - Returns 401 for unknown email or wrong password (same message for both
      to avoid user-enumeration).
    - Returns a signed JWT on success.
    """
    users = get_users_collection()

    user = await users.find_one({"email": body.email})
    if not user or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = str(user["_id"])
    token = create_access_token(user_id)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
async def get_me(user_id: str = Depends(get_current_user)) -> Dict[str, str]:
    """Return the authenticated user's ID.

    Requires a valid Authorization: Bearer <token> header.
    Returns 401 if the token is missing, expired, or invalid.
    """
    return {"user_id": user_id}
