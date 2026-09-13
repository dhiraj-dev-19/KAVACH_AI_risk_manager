"""
transactions_router.py — CSV upload and scoring pipeline for JUDGE.

Routes:
    POST /transactions/upload-csv  — protected; parse CSV, score rows via the
                                     existing XGBoost pipeline, store in MongoDB.

Column contract (8 required raw input columns):
    transaction_id, timestamp, merchant, merchant_category,
    amount, card_num, device_id, declined

If any column is missing the endpoint returns HTTP 422 with a clear diff of
detected vs required columns — it never silently guesses or fills in values.
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


# ── Route ─────────────────────────────────────────────────────────────────────

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
        stores raw row + scoring output in MongoDB tagged with user_id and
        upload_batch_id. Returns a summary of the batch.
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

    # ── 3. Score each row through the EXISTING pipeline ───────────────────────
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

        # Call the EXISTING scoring function — zero new logic
        try:
            scored = score_transaction(row_dict)
        except Exception as exc:
            errors.append({
                "row_index": int(idx),
                "transaction_id": row_dict.get("transaction_id", f"row-{idx}"),
                "error": str(exc),
            })
            continue

        # Build the MongoDB document
        mongo_doc = {
            # Raw row fields (all columns present in the CSV)
            **{k: (v if not pd.isna(v) else None) for k, v in row_dict.items()},
            # Scoring outputs from the EXISTING pipeline
            "risk_score": scored.get("risk_score"),
            "features": scored.get("features"),
            "cohort_context": scored.get("cohort_context"),
            "scoring_latency_ms": scored.get("scoring_latency_ms"),
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
        })

    # ── 4. Persist to MongoDB ─────────────────────────────────────────────────
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
