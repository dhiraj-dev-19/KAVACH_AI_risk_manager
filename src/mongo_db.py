"""
mongo_db.py — Motor (async MongoDB) client singleton for JUDGE.

Exposes:
    get_client()                 -> AsyncIOMotorClient  (lazy singleton)
    get_users_collection()       -> AsyncIOMotorCollection
    get_transactions_collection()-> AsyncIOMotorCollection
    close_client()               -> None  (call on app shutdown)

Database name: judge_db
Collections  : users, transactions

Environment variables read:
    MONGO_URI — Atlas connection string (required)
"""

import os
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

# ── Module-level singleton ────────────────────────────────────────────────────
_client: Optional[AsyncIOMotorClient] = None

_DB_NAME = "judge_db"


def _get_mongo_uri() -> str:
    uri = os.getenv("MONGO_URI", "")
    if not uri or uri.startswith("<"):
        raise RuntimeError(
            "MONGO_URI is not configured. Set it in your .env file."
        )
    return uri


def get_client() -> AsyncIOMotorClient:
    """Return the shared Motor client, creating it on first call."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            _get_mongo_uri(),
            serverSelectionTimeoutMS=10_000,
        )
    return _client


def close_client() -> None:
    """Close the Motor client — call from app shutdown lifespan hook."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_users_collection() -> AsyncIOMotorCollection:
    """Return the `users` collection in judge_db."""
    return get_client()[_DB_NAME]["users"]


def get_transactions_collection() -> AsyncIOMotorCollection:
    """Return the `transactions` collection in judge_db."""
    return get_client()[_DB_NAME]["transactions"]
