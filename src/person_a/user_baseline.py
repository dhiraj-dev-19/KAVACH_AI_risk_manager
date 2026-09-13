"""
user_baseline.py — Per-user personal transaction baseline layer for JUDGE.

This module provides a NEW, USER-based personal baseline that runs IN PARALLEL
with the existing XGBoost model pipeline. It never touches FEATURE_COLUMNS, never
calls score_transaction(), and never modifies the model or merchant-based baselines.

Exposes:
    compute_user_baseline(user_id)               -> dict  (async, queries MongoDB)
    compute_personal_deviation(transaction, baseline) -> dict  (sync, pure math)

Design contract:
    • If a user has < 5 transactions, compute_user_baseline returns
      {"insufficient_history": True} to avoid meaningless stats / divide-by-zero.
    • compute_personal_deviation safely propagates insufficient_history when present.
    • amount_zscore is the USER's own personal z-score — entirely separate from the
      MERCHANT-based amount_baseline_zscore used by the XGBoost model.
"""

import os
import sys
from typing import Any, Dict, List

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.mongo_db import get_transactions_collection


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def compute_user_baseline(user_id: str) -> Dict[str, Any]:
    """Query this user's historical transactions from MongoDB and return baseline stats.

    Returns a dict with:
        avg_amount       (float)
        stddev_amount    (float)
        top_categories   (list[str])  — up to 5, by frequency
        typical_hours    (list[int])  — hour-of-day values with ≥ 2 occurrences
        transaction_count (int)

    Returns {"insufficient_history": True} when transaction_count < 5, which prevents
    divide-by-zero on stddev and avoids meaningless baselines for brand-new users.
    """
    col = get_transactions_collection()

    # ── 1. Count + amount stats in one aggregation ────────────────────────────
    stats_pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$group": {
                "_id": None,
                "transaction_count": {"$sum": 1},
                "avg_amount": {"$avg": "$amount"},
                "stddev_amount": {"$stdDevPop": "$amount"},
            }
        },
    ]
    stats_cursor = col.aggregate(stats_pipeline)
    stats_docs = await stats_cursor.to_list(length=1)

    if not stats_docs:
        return {"insufficient_history": True}

    stats = stats_docs[0]
    tx_count = int(stats.get("transaction_count", 0))

    if tx_count < 5:
        return {"insufficient_history": True}

    avg_amount = float(stats.get("avg_amount") or 0.0)
    stddev_amount = float(stats.get("stddev_amount") or 0.0)

    # ── 2. Top categories by frequency (up to 5) ─────────────────────────────
    cat_pipeline = [
        {"$match": {"user_id": user_id, "merchant_category": {"$exists": True}}},
        {"$group": {"_id": "$merchant_category", "cnt": {"$sum": 1}}},
        {"$sort": {"cnt": -1}},
        {"$limit": 5},
    ]
    cat_cursor = col.aggregate(cat_pipeline)
    cat_docs = await cat_cursor.to_list(length=5)
    top_categories: List[str] = [
        str(d["_id"]) for d in cat_docs if d.get("_id") is not None
    ]

    # ── 3. Typical hours — hours with ≥ 2 transactions ───────────────────────
    # uploaded_at is stored as an ISO string; we parse it into a date object and
    # extract the hour from it using $dateFromString then $hour.
    hour_pipeline = [
        {"$match": {"user_id": user_id, "uploaded_at": {"$exists": True}}},
        {
            "$project": {
                "hour": {
                    "$hour": {
                        "$dateFromString": {
                            "dateString": "$uploaded_at",
                            "onError": None,
                            "onNull": None,
                        }
                    }
                }
            }
        },
        {"$match": {"hour": {"$ne": None}}},
        {"$group": {"_id": "$hour", "cnt": {"$sum": 1}}},
        {"$match": {"cnt": {"$gte": 2}}},
        {"$sort": {"_id": 1}},
    ]
    hour_cursor = col.aggregate(hour_pipeline)
    hour_docs = await hour_cursor.to_list(length=24)
    typical_hours: List[int] = [int(d["_id"]) for d in hour_docs]

    return {
        "avg_amount": avg_amount,
        "stddev_amount": stddev_amount,
        "top_categories": top_categories,
        "typical_hours": typical_hours,
        "transaction_count": tx_count,
    }


# ---------------------------------------------------------------------------
# Public sync API (pure math, no I/O)
# ---------------------------------------------------------------------------

def compute_personal_deviation(
    transaction: Dict[str, Any],
    baseline: Dict[str, Any],
) -> Dict[str, Any]:
    """Given one transaction and a pre-computed user baseline, return deviation signals.

    Returns a dict with:
        amount_zscore   (float)  — vs this user's own avg/stddev, NOT the merchant zscore
        category_match  (bool)   — is merchant_category in baseline top_categories?
        time_match      (bool)   — is transaction hour in baseline typical_hours?

    When baseline has insufficient_history, returns {"insufficient_history": True}.

    This result is stored as "personal_context" in MongoDB and returned in the upload
    response. It is NEVER passed into score_transaction() or the FEATURE_COLUMNS vector.
    """
    if baseline.get("insufficient_history"):
        return {"insufficient_history": True}

    # Amount z-score vs user's own distribution
    amount = float(transaction.get("amount") or 0.0)
    avg = float(baseline.get("avg_amount") or 0.0)
    std = float(baseline.get("stddev_amount") or 0.0)
    amount_zscore = round((amount - avg) / (std + 1e-5), 4)

    # Category match
    category = str(transaction.get("merchant_category") or "")
    top_categories: List[str] = baseline.get("top_categories") or []
    category_match: bool = category in top_categories

    # Time match — extract hour from the transaction timestamp
    import pandas as pd  # local import to avoid top-level dep if not needed
    try:
        ts = pd.to_datetime(transaction.get("timestamp") or pd.Timestamp.now())
        txn_hour: int = int(ts.hour)
    except Exception:
        txn_hour = -1  # sentinel — won't match any typical hour

    typical_hours: List[int] = baseline.get("typical_hours") or []
    time_match: bool = txn_hour in typical_hours

    return {
        "amount_zscore": amount_zscore,
        "category_match": category_match,
        "time_match": time_match,
    }
