"""
transactions_router.py — CSV upload and scoring pipeline for JUDGE.

Routes:
    POST /transactions/upload-csv          — protected; parse CSV, score rows via the
                                             existing XGBoost pipeline, compute per-user
                                             personal baseline, store in MongoDB.
    GET  /transactions/batches             — protected; list this user's upload batches.
    GET  /transactions/batches/{batch_id}  — protected; detail for one batch (403 if
                                             the batch belongs to a different user).

Column contract (8 required raw input columns):
    transaction_id, timestamp, merchant, merchant_category,
    amount, card_num, device_id, declined

If any column is missing the endpoint returns HTTP 422 with a clear diff of
detected vs required columns — it never silently guesses or fills in values.

Phase 3 addition:
    After the existing score_transaction() call, compute_user_baseline() and
    compute_personal_deviation() are called to produce a "personal_context" dict
    that is stored in MongoDB and returned in the response.  Nothing from
    personal_context is passed into score_transaction() or the FEATURE_COLUMNS vector.
"""

import io
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.auth import get_current_user
from src.mongo_db import get_transactions_collection

# Import the EXISTING scoring function — no new logic here.
from src.person_a.scoring_service import score_transaction

# Phase 3: per-user personal baseline (parallel layer, never touches FEATURE_COLUMNS)
from src.person_a.user_baseline import compute_personal_deviation, compute_user_baseline

router = APIRouter(prefix="/transactions", tags=["Transactions"])

# ── Column contract ───────────────────────────────────────────────────────────
REQUIRED_COLUMNS: List[str] = [
    "transaction_id",
    "timestamp",
    "merchant",
    "merchant_category",
    "amount",
    "card_num",
    "device_id",
    "declined",
]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/upload-csv")
async def upload_csv(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upload a CSV of transactions, score them, and persist to MongoDB.

    Requires Authorization: Bearer <token>.

    On column mismatch:
        Returns HTTP 422 with detected_columns, required_columns, missing_columns.

    On success:
        Scores each row with the existing XGBoost pipeline (score_transaction),
        computes personal_context via the new per-user baseline layer,
        stores raw row + scoring output + personal_context in MongoDB tagged with
        user_id and upload_batch_id.  Returns a summary of the batch.

    personal_context fields (NEVER passed to score_transaction or FEATURE_COLUMNS):
        amount_zscore   — vs this user's own historical average, not the merchant one
        category_match  — bool: is this category in user's top categories?
        time_match      — bool: does this hour fall in the user's typical hours?
        insufficient_history — True when user has < 5 prior transactions
    """
    # ── 1. Read & parse ───────────────────────────────────────────────────────
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are accepted.",
        )

    raw_bytes = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(raw_bytes))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse CSV: {exc}",
        )

    if df.empty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded CSV contains no rows.",
        )

    # ── 2. Column validation ──────────────────────────────────────────────────
    detected_columns = list(df.columns)
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in detected_columns]

    if missing_columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "column_mismatch",
                "message": (
                    "The CSV is missing required columns. "
                    "Please add the missing columns and re-upload."
                ),
                "detected_columns": detected_columns,
                "required_columns": REQUIRED_COLUMNS,
                "missing_columns": missing_columns,
            },
        )

    # ── 3. Compute per-user baseline ONCE before the row loop ─────────────────
    # All rows in this batch share the same user_id.  The baseline reflects the
    # user's history BEFORE this upload (correct — we read before writing).
    user_baseline = await compute_user_baseline(user_id)

    # ── 4. Score each row through the EXISTING pipeline ───────────────────────
    upload_batch_id = str(uuid.uuid4())
    uploaded_at = datetime.now(timezone.utc).isoformat()

    mongo_docs: List[Dict[str, Any]] = []
    results_summary: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        row_dict = row.to_dict()

        # Coerce types that scoring_service expects
        try:
            row_dict["amount"] = float(row_dict.get("amount", 0.0))
            row_dict["declined"] = int(row_dict.get("declined", 0))
        except (ValueError, TypeError):
            pass  # scoring_service has its own safe defaults

        # Call the EXISTING scoring function — zero new logic, unchanged contract
        try:
            scored = score_transaction(row_dict)
        except Exception as exc:
            errors.append({
                "row_index": int(idx),
                "transaction_id": row_dict.get("transaction_id", f"row-{idx}"),
                "error": str(exc),
            })
            continue

        # Phase 3: compute personal deviation for this row against user baseline.
        # This never touches score_transaction() or FEATURE_COLUMNS.
        personal_context = compute_personal_deviation(row_dict, user_baseline)

        # Build the MongoDB document
        mongo_doc = {
            # Raw row fields (all columns present in the CSV)
            **{k: (v if not pd.isna(v) else None) for k, v in row_dict.items()},
            # Scoring outputs from the EXISTING pipeline (unchanged)
            "risk_score": scored.get("risk_score"),
            "features": scored.get("features"),
            "cohort_context": scored.get("cohort_context"),
            "scoring_latency_ms": scored.get("scoring_latency_ms"),
            # Phase 3: personal context (new field — does not overwrite any existing field)
            "personal_context": personal_context,
            # Upload metadata
            "user_id": user_id,
            "upload_batch_id": upload_batch_id,
            "uploaded_at": uploaded_at,
        }
        mongo_docs.append(mongo_doc)

        results_summary.append({
            "transaction_id": scored.get("transaction_id"),
            "risk_score": scored.get("risk_score"),
            "merchant": scored.get("merchant"),
            "amount": scored.get("amount"),
            # Phase 3: expose personal_context per row in the response
            "personal_context": personal_context,
        })

    # ── 5. Persist to MongoDB ─────────────────────────────────────────────────
    if mongo_docs:
        transactions = get_transactions_collection()
        await transactions.insert_many(mongo_docs)

    return {
        "upload_batch_id": upload_batch_id,
        "rows_processed": len(mongo_docs),
        "rows_errored": len(errors),
        "results_summary": results_summary,
        "errors": errors if errors else None,
    }


@router.get("/batches")
async def list_batches(
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """List this user's upload batches, grouped and sorted by recency.

    Returns:
        batches: List of { batch_id, created_at, row_count, flagged_count }
        sorted by created_at descending (most recent first).

    flagged_count uses risk_score > 0.29 (the trained model's optimal threshold).
    Only batches belonging to the requesting user_id are returned.
    """
    transactions = get_transactions_collection()

    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$group": {
                "_id": "$upload_batch_id",
                "created_at": {"$min": "$uploaded_at"},
                "row_count": {"$sum": 1},
                "flagged_count": {
                    "$sum": {
                        "$cond": [{"$gt": ["$risk_score", 0.29]}, 1, 0]
                    }
                },
            }
        },
        {"$sort": {"created_at": -1}},
    ]

    cursor = transactions.aggregate(pipeline)
    docs = await cursor.to_list(length=1000)

    batches = [
        {
            "batch_id": d["_id"],
            "created_at": d["created_at"],
            "row_count": d["row_count"],
            "flagged_count": d["flagged_count"],
        }
        for d in docs
        if d.get("_id")  # skip any docs without a batch id
    ]

    return {"batches": batches}


@router.get("/batches/{batch_id}")
async def get_batch_detail(
    batch_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return all transactions + scores + personal_context for a single batch.

    Ownership check: returns HTTP 403 if the batch_id belongs to a different user.
    Only transactions belonging to the requesting user_id are returned.
    """
    transactions = get_transactions_collection()

    # ── Ownership verification ────────────────────────────────────────────────
    # Try to find any doc with this batch_id that belongs to this user.
    # If none found, the batch either doesn't exist or belongs to another user —
    # in both cases we return 403 (avoids leaking whether the batch exists at all).
    ownership_doc = await transactions.find_one(
        {"upload_batch_id": batch_id, "user_id": user_id},
        projection={"_id": 1},
    )
    if ownership_doc is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Batch not found or access denied.",
        )

    # ── Fetch all rows for this batch ─────────────────────────────────────────
    cursor = transactions.find(
        {"upload_batch_id": batch_id},
        # Exclude the internal Mongo _id to keep the response clean
        projection={"_id": 0},
    )
    rows = await cursor.to_list(length=10_000)

    return {
        "batch_id": batch_id,
        "transaction_count": len(rows),
        "transactions": rows,
    }
