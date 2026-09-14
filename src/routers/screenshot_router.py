"""
screenshot_router.py — Screenshot upload and scoring endpoint for JUDGE.

Route:
    POST /transactions/upload-screenshot — protected; extract single transaction from image via
                                          Gemini vision, score via existing XGBoost pipeline,
                                          compute per-user personal baseline, store in MongoDB
                                          with source_type: "screenshot" and inferred_fields.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.auth import get_current_user
from src.mongo_db import get_transactions_collection

# Import the EXISTING scoring function — unchanged
from src.person_a.scoring_service import score_transaction

# Per-user personal baseline (parallel layer, never touches FEATURE_COLUMNS)
from src.person_a.user_baseline import compute_personal_deviation, compute_user_baseline

# Screenshot extraction via Gemini vision (Phase 6)
from src.person_b.screenshot_parser import extract_transaction_from_screenshot

router = APIRouter(prefix="/transactions", tags=["Transactions"])

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/octet-stream",
}


@router.post("/upload-screenshot")
async def upload_screenshot(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upload a payment screenshot, extract transaction details using Gemini vision, score it, and persist to MongoDB.

    Requires Authorization: Bearer <token>.

    Error responses:
        HTTP 400 — empty file or unsupported content type
        HTTP 422 — extraction failed / unreadable screenshot

    On success:
        Scores the extracted transaction with score_transaction(),
        computes personal_context via compute_user_baseline() and compute_personal_deviation(),
        stores in MongoDB with source_type: "screenshot" and inferred_fields tracking.
        Returns {batch_id, rows_processed: 1, results_summary}.
    """
    # ── 1. Basic validation ───────────────────────────────────────────────────
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: '{file.content_type}'. Please upload a PNG, JPEG, or WebP image.",
        )

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded screenshot file is empty.",
        )

    # ── 2. Extract transaction via Gemini Vision ──────────────────────────────
    extraction_result = extract_transaction_from_screenshot(raw_bytes)

    if not extraction_result or extraction_result.get("error") == "extraction_failed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "extraction_failed",
                "message": (
                    "Could not extract clear transaction details from this screenshot. "
                    "Please try uploading a clearer, higher-resolution image, "
                    "or enter the transaction using CSV or PDF upload instead."
                ),
            },
        )

    row_dict = extraction_result
    inferred_fields: List[str] = row_dict.pop("inferred_fields", [])

    # Coerce types for scoring service
    try:
        row_dict["amount"] = float(row_dict.get("amount", 0.0))
        row_dict["declined"] = int(row_dict.get("declined", 0))
    except (ValueError, TypeError):
        pass

    # ── 3. Score through the EXISTING pipeline ────────────────────────────────
    try:
        scored = score_transaction(row_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scoring pipeline error: {exc}",
        )

    # ── 4. Compute personal deviation against user baseline ───────────────────
    user_baseline = await compute_user_baseline(user_id)
    personal_context = compute_personal_deviation(row_dict, user_baseline)

    upload_batch_id = str(uuid.uuid4())
    uploaded_at = datetime.now(timezone.utc).isoformat()

    # ── 5. Build MongoDB document ─────────────────────────────────────────────
    mongo_doc = {
        # Raw extracted fields with placeholders
        **{k: v for k, v in row_dict.items()},
        # Scoring outputs from the EXISTING pipeline (unchanged)
        "risk_score": scored.get("risk_score"),
        "features": scored.get("features"),
        "cohort_context": scored.get("cohort_context"),
        "scoring_latency_ms": scored.get("scoring_latency_ms"),
        # Personal context
        "personal_context": personal_context,
        # Upload metadata
        "user_id": user_id,
        "upload_batch_id": upload_batch_id,
        "uploaded_at": uploaded_at,
        "source_type": "screenshot",
        "inferred_fields": inferred_fields,
    }

    transactions = get_transactions_collection()
    await transactions.insert_one(mongo_doc)

    results_summary = [
        {
            "transaction_id": scored.get("transaction_id"),
            "risk_score": scored.get("risk_score"),
            "merchant": scored.get("merchant"),
            "amount": scored.get("amount"),
            "personal_context": personal_context,
            "inferred_fields": inferred_fields,
        }
    ]

    return {
        "batch_id": upload_batch_id,
        "rows_processed": 1,
        "results_summary": results_summary,
    }
