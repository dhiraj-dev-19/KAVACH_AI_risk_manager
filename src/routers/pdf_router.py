"""
pdf_router.py — PDF upload and scoring endpoint for JUDGE.

Route:
    POST /transactions/upload-pdf — protected; parse text-based PDF bank statement,
                                     score rows via the existing XGBoost pipeline,
                                     compute per-user personal baseline, store in MongoDB
                                     with source_type: "pdf".

Column contract (8 required raw input columns):
    transaction_id, timestamp, merchant, merchant_category,
    amount, card_num, device_id, declined
"""

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

# Per-user personal baseline (parallel layer, never touches FEATURE_COLUMNS)
from src.person_a.user_baseline import compute_personal_deviation, compute_user_baseline

# PDF text extraction (Phase 5 — our new module)
from src.person_b.pdf_parser import extract_transactions_from_pdf

router = APIRouter(prefix="/transactions", tags=["Transactions"])

# ── Column contract (reimplemented locally — not imported from transactions_router) ──
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


@router.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upload a PDF bank statement, extract transactions, score them, and persist to MongoDB.

    Requires Authorization: Bearer <token>.

    Error responses:
        HTTP 400 — file is not a PDF
        HTTP 422 — scanned/image PDF (no text extractable)
        HTTP 422 — extracted rows are missing required columns
        HTTP 422 — no transactions could be parsed from the PDF

    On success:
        Scores each row with the existing XGBoost pipeline (score_transaction),
        computes personal_context via the per-user baseline layer,
        stores raw row + scoring output + personal_context in MongoDB tagged with
        user_id, upload_batch_id, and source_type: "pdf".
    """
    # ── 1. Basic file validation ──────────────────────────────────────────────
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .pdf files are accepted.",
        )

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded PDF file is empty.",
        )

    # ── 2. Extract transactions from PDF ──────────────────────────────────────
    extraction_result = extract_transactions_from_pdf(raw_bytes)

    # Handle scanned-PDF error signal
    if isinstance(extraction_result, dict) and extraction_result.get("error") == "scanned_pdf_not_supported":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "scanned_pdf_not_supported",
                "message": (
                    "This PDF appears to be a scanned/image-only document. "
                    "Please upload a text-based PDF bank statement, or use "
                    "CSV upload or screenshot capture instead."
                ),
            },
        )

    # Empty extraction — format not parseable
    if not extraction_result or (isinstance(extraction_result, list) and len(extraction_result) == 0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "no_transactions_parsed",
                "message": (
                    "Could not parse any transactions from this PDF. "
                    "Please ensure the document is a bank/card statement in a "
                    "tabular format, or use CSV upload instead."
                ),
            },
        )

    rows: List[Dict[str, Any]] = extraction_result  # type: ignore[assignment]

    # ── 3. Column validation (reimplemented locally, same pattern as CSV route) ─
    for idx, row in enumerate(rows):
        detected_columns = list(row.keys())
        missing_columns = [c for c in REQUIRED_COLUMNS if c not in detected_columns]
        if missing_columns:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "column_mismatch",
                    "message": (
                        f"Row {idx} extracted from the PDF is missing required columns. "
                        "The PDF format may not be fully supported."
                    ),
                    "detected_columns": detected_columns,
                    "required_columns": REQUIRED_COLUMNS,
                    "missing_columns": missing_columns,
                },
            )

    # ── 4. Compute per-user baseline ONCE before the row loop ─────────────────
    user_baseline = await compute_user_baseline(user_id)

    # ── 5. Score each row through the EXISTING pipeline ───────────────────────
    upload_batch_id = str(uuid.uuid4())
    uploaded_at = datetime.now(timezone.utc).isoformat()

    mongo_docs: List[Dict[str, Any]] = []
    results_summary: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for idx, row_dict in enumerate(rows):
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
                "row_index": idx,
                "transaction_id": row_dict.get("transaction_id", f"row-{idx}"),
                "error": str(exc),
            })
            continue

        # Compute personal deviation for this row against user baseline
        personal_context = compute_personal_deviation(row_dict, user_baseline)

        # Build the MongoDB document (same shape as CSV upload path + source_type)
        mongo_doc = {
            # Raw row fields
            **{k: v for k, v in row_dict.items()},
            # Scoring outputs from the EXISTING pipeline (unchanged)
            "risk_score": scored.get("risk_score"),
            "features": scored.get("features"),
            "cohort_context": scored.get("cohort_context"),
            "scoring_latency_ms": scored.get("scoring_latency_ms"),
            # Personal context (never passed to score_transaction or FEATURE_COLUMNS)
            "personal_context": personal_context,
            # Upload metadata
            "user_id": user_id,
            "upload_batch_id": upload_batch_id,
            "uploaded_at": uploaded_at,
            "source_type": "pdf",
        }
        mongo_docs.append(mongo_doc)

        results_summary.append({
            "transaction_id": scored.get("transaction_id"),
            "risk_score": scored.get("risk_score"),
            "merchant": scored.get("merchant"),
            "amount": scored.get("amount"),
            "personal_context": personal_context,
        })

    # ── 6. Persist to MongoDB ─────────────────────────────────────────────────
    if mongo_docs:
        transactions = get_transactions_collection()
        await transactions.insert_many(mongo_docs)

    return {
        "batch_id": upload_batch_id,
        "rows_processed": len(mongo_docs),
        "rows_errored": len(errors),
        "results_summary": results_summary,
        "errors": errors if errors else None,
    }
