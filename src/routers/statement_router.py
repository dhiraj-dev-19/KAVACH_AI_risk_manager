"""
statement_router.py — 2-step API flow for real-world bank statements (CSV/PDF).

Routes:
    POST /statements/extract — Accepts CSV/PDF, parses via heuristic parser, 
                               returns preview_rows and mapped schema. Does not score.
    POST /statements/confirm — Accepts confirmed JSON rows, computes user baseline once, 
                               scores, and persists.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status, Body

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.auth import get_current_user
from src.mongo_db import get_transactions_collection
from src.person_a.scoring_service import score_transaction
from src.person_a.user_baseline import compute_personal_deviation, compute_user_baseline
from src.person_b.heuristic_statement_parser import extract_transactions_from_csv, extract_transactions_from_pdf
from src.person_b.schema_mapper import REQUIRED_COLUMNS

router = APIRouter(prefix="/statements", tags=["Statements"])


@router.post("/extract")
async def extract_statement(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Step 1: Extract and map columns from a raw bank statement.
    Does NOT score or persist data. Requires explicit confirmation in Step 2.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    filename_lower = file.filename.lower()
    raw_bytes = await file.read()
    
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    # Route to the appropriate heuristic parser
    if filename_lower.endswith(".csv"):
        extraction_result = extract_transactions_from_csv(raw_bytes)
    elif filename_lower.endswith(".pdf"):
        extraction_result = extract_transactions_from_pdf(raw_bytes)
    else:
        raise HTTPException(status_code=400, detail="Only .csv and .pdf files are supported.")

    # Handle errors returned from parser
    if isinstance(extraction_result, dict) and "error" in extraction_result:
        # Map specific internal errors to appropriate HTTP status codes
        if extraction_result["error"] == "scanned_pdf_not_supported":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=extraction_result,
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=extraction_result,
        )
        
    if not extraction_result or not isinstance(extraction_result, dict) or not extraction_result.get("valid_rows"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "no_transactions_parsed", "message": "Could not parse any transactions from this file."}
        )

    # Basic structural validation to ensure the preview is safe
    rows = extraction_result.get("valid_rows", [])
    dropped_rows = extraction_result.get("dropped_rows", [])

    for idx, row in enumerate(rows):
        detected = list(row.keys())
        missing = [c for c in REQUIRED_COLUMNS if c not in detected]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "mapping_failure",
                    "message": f"Row {idx} is missing required mapped columns.",
                    "missing_columns": missing
                }
            )

    return {
        "status": "extracted",
        "message": "Please review the proposed mapping and confirm.",
        "mapped_schema": REQUIRED_COLUMNS,
        "preview_rows": rows,
        "dropped_rows": dropped_rows
    }


@router.post("/confirm")
async def confirm_statement(
    preview_rows: List[Dict[str, Any]] = Body(...),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Step 2: Score and persist a confirmed JSON array of transactions.
    """
    if not preview_rows:
        raise HTTPException(status_code=400, detail="No rows provided for confirmation.")

    # 1. Compute per-user baseline ONCE before the row loop
    user_baseline = await compute_user_baseline(user_id)

    # 2. Score each row through the EXISTING pipeline
    upload_batch_id = str(uuid.uuid4())
    uploaded_at = datetime.now(timezone.utc).isoformat()

    mongo_docs: List[Dict[str, Any]] = []
    results_summary: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for idx, row_dict in enumerate(preview_rows):
        # Coerce types that scoring_service expects
        try:
            row_dict["amount"] = float(row_dict.get("amount", 0.0))
            declined = row_dict.get("declined")
            # Handle both boolean and int forms cleanly
            if isinstance(declined, bool):
                row_dict["declined"] = 1 if declined else 0
            else:
                row_dict["declined"] = int(declined) if declined else 0
        except (ValueError, TypeError):
            pass  

        # Call the EXISTING scoring function
        try:
            scored = score_transaction(row_dict)
        except Exception as exc:
            errors.append({
                "row_index": idx,
                "transaction_id": row_dict.get("transaction_id", f"row-{idx}"),
                "error": str(exc),
            })
            continue

        # Compute personal deviation
        personal_context = compute_personal_deviation(row_dict, user_baseline)

        # Build MongoDB document
        mongo_doc = {
            # Raw row fields
            **{k: v for k, v in row_dict.items()},
            # Scoring outputs
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
            "source_type": "statement",
        }
        mongo_docs.append(mongo_doc)

        results_summary.append({
            "transaction_id": scored.get("transaction_id"),
            "risk_score": scored.get("risk_score"),
            "merchant": scored.get("merchant"),
            "amount": scored.get("amount"),
            "personal_context": personal_context,
        })

    # 3. Persist to MongoDB
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
