"""
pdf_parser.py — Extract transactions from text-based PDF bank statements.

Exposes:
    extract_transactions_from_pdf(file_bytes: bytes) -> list[dict] | dict

Design:
    • Uses pdfplumber for text extraction (text-based PDFs only).
    • If pdfplumber extracts NO text at all (likely a scanned/image PDF),
      returns {"error": "scanned_pdf_not_supported"} — no OCR is attempted.
    • Parses extracted text into rows matching the 8 required raw input columns:
        transaction_id, timestamp, merchant, merchant_category,
        amount, card_num, device_id, declined
    • If a bank statement's format can't be confidently parsed, returns [].
"""

import io
import json
import os
import re
import sys
from typing import Any, Dict, List, Union

from dotenv import load_dotenv
import pdfplumber

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
MODEL_NAME = "gemini-3.5-flash"

def _get_genai_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(
                    attempts=1,
                    initial_delay=1.5,
                    max_delay=10.0,
                    http_status_codes=[429, 500, 502, 503, 504],
                )
            ),
        )
    except Exception as e:
        print(f"[pdf_parser] Gemini client init warning: {e}")
        return None

def _clean_json_text(text: str) -> str:
    text = text.strip()
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if code_block:
        return code_block.group(1).strip()
    brace_match = re.search(r"(\[[\s\S]*\])", text)
    if brace_match:
        return brace_match.group(1).strip()
    return text

def _call_gemini_fallback(file_bytes: bytes) -> List[Dict[str, Any]]:
    client = _get_genai_client()
    if not client:
        return []
    
    try:
        from google.genai import types
        pdf_part = types.Part.from_bytes(data=file_bytes, mime_type="application/pdf")
        prompt = (
            "You are an automated transaction parser. Examine this PDF bank statement "
            "and extract ALL transaction rows into a single JSON array of objects.\n\n"
            "Each object must have exactly these keys:\n"
            "- transaction_id: (string, e.g. UTR or null)\n"
            "- timestamp: (string, YYYY-MM-DD HH:MM:SS or null)\n"
            "- merchant: (string, the merchant name)\n"
            "- merchant_category: (string, category or null)\n"
            "- amount: (number, float)\n"
            "- card_num: (string, or null)\n"
            "- device_id: (string, or null)\n"
            "- declined: (boolean, 1/true if failed, 0/false if success)\n\n"
            "Output ONLY the JSON array without markdown formatting."
        )
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[prompt, pdf_part],
            )
        except Exception as e:
            print(f"[pdf_parser] Primary model {MODEL_NAME} failed ({e}), falling back to gemini-2.5-flash")
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=[prompt, pdf_part],
            )
        if response and response.text:
            cleaned = _clean_json_text(response.text)
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                clean_rows = []
                for row in parsed:
                    clean_row = {}
                    for col in REQUIRED_COLUMNS:
                        val = row.get(col)
                        clean_row[col] = _clean_cell(col, val) if val is not None else None
                        
                    if _is_valid_row(clean_row):
                        clean_rows.append(clean_row)
                return clean_rows
    except Exception as e:
        print(f"[pdf_parser] Gemini fallback error: {e}")
    return []


# The 8 raw columns the scoring pipeline expects per transaction row
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


def extract_transactions_from_pdf(
    file_bytes: bytes,
) -> Union[List[Dict[str, Any]], Dict[str, str]]:
    """Extract transaction rows from a text-based PDF bank statement.

    Returns:
        list[dict]  — parsed rows (each dict has the 8 required raw columns),
                       or an empty list if the format cannot be confidently parsed.
        dict        — {"error": "scanned_pdf_not_supported"} when no text is found.
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
    except Exception:
        return {"error": "scanned_pdf_not_supported"}

    # ── 1. Collect all text across pages ──────────────────────────────────────
    all_text = ""
    for page in pdf.pages:
        page_text = page.extract_text()
        if page_text:
            all_text += page_text + "\n"

    pdf.close()

    # If pdfplumber extracted no text at all → scanned / image-only PDF
    if not all_text.strip():
        # Fallback to Gemini 1.5 Pro for scanned PDFs
        gemini_rows = _call_gemini_fallback(file_bytes)
        if gemini_rows:
            return gemini_rows
        return {"error": "scanned_pdf_not_supported"}

    # ── 2. Try table-based extraction first ───────────────────────────────────
    rows = _try_table_extraction(file_bytes)
    if rows:
        return rows

    # ── 3. Fall back to line-by-line regex parsing ────────────────────────────
    rows = _try_line_parsing(all_text)
    if rows:
        return rows

    # ── 4. Fall back to Gemini for unparseable complex layouts ────────────────
    gemini_rows = _call_gemini_fallback(file_bytes)
    if gemini_rows:
        return gemini_rows

    # Could not confidently parse — return empty list per spec
    return []


def _try_table_extraction(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Attempt to extract rows from pdfplumber's table detection."""
    results: List[Dict[str, Any]] = []

    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
    except Exception:
        return []

    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if not table or len(table) < 2:
                continue

            # Normalise header row
            raw_header = [
                str(h).strip().lower().replace(" ", "_") if h else ""
                for h in table[0]
            ]

            # Check if header contains all required columns
            if not all(col in raw_header for col in REQUIRED_COLUMNS):
                # Try common header aliases
                mapped_header = _map_header_aliases(raw_header)
                if not all(col in mapped_header for col in REQUIRED_COLUMNS):
                    continue
                raw_header = mapped_header

            # Parse data rows
            for data_row in table[1:]:
                if not data_row or len(data_row) != len(raw_header):
                    continue
                row_dict = {}
                for col_name, cell_val in zip(raw_header, data_row):
                    if col_name in REQUIRED_COLUMNS:
                        row_dict[col_name] = _clean_cell(col_name, cell_val)
                if _is_valid_row(row_dict):
                    results.append(row_dict)

    pdf.close()
    return results


def _try_line_parsing(text: str) -> List[Dict[str, Any]]:
    """Attempt to parse transactions from free-form text lines.

    Looks for lines that contain recognisable transaction patterns:
    a transaction ID, a timestamp-like string, and a monetary amount.
    """
    results: List[Dict[str, Any]] = []
    lines = text.strip().split("\n")

    # Check if first non-blank line looks like a CSV-style header
    header_line = None
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        # Heuristic: if the line contains several required column names, treat
        # it as a header row and parse subsequent lines as delimited data.
        matches = sum(1 for col in REQUIRED_COLUMNS if col in lower.replace(" ", "_"))
        if matches >= 5:
            header_line = stripped
            data_start = i + 1
            break

    if header_line:
        return _parse_delimited_lines(header_line, lines[data_start:])

    # Regex-based heuristic for statement-like lines
    # Pattern: TXN-ID  TIMESTAMP  MERCHANT  CATEGORY  AMOUNT  CARD  DEVICE  DECLINED
    txn_pattern = re.compile(
        r"(TXN[-_]?\w+)"          # transaction_id
        r"\s+"
        r"(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}(?::\d{2})?)"  # timestamp
        r"\s+"
        r"(\S+)"                   # merchant
        r"\s+"
        r"(\S+)"                   # merchant_category
        r"\s+"
        r"(\d+\.?\d*)"            # amount
        r"\s+"
        r"(\S+)"                   # card_num
        r"\s+"
        r"(\S+)"                   # device_id
        r"\s+"
        r"([01])",                 # declined
        re.IGNORECASE,
    )

    for line in lines:
        m = txn_pattern.search(line)
        if m:
            row = {
                "transaction_id": m.group(1),
                "timestamp": m.group(2),
                "merchant": m.group(3),
                "merchant_category": m.group(4),
                "amount": _safe_float(m.group(5)),
                "card_num": m.group(6),
                "device_id": m.group(7),
                "declined": int(m.group(8)),
            }
            results.append(row)

    return results


def _parse_delimited_lines(
    header_line: str, data_lines: List[str]
) -> List[Dict[str, Any]]:
    """Parse CSV/TSV-style lines using the detected header."""
    # Detect delimiter
    if "\t" in header_line:
        delimiter = "\t"
    elif "," in header_line:
        delimiter = ","
    else:
        # Try whitespace with at least 2 spaces as separator
        delimiter = None

    if delimiter:
        raw_cols = [c.strip().lower().replace(" ", "_") for c in header_line.split(delimiter)]
    else:
        raw_cols = [c.strip().lower().replace(" ", "_") for c in re.split(r"\s{2,}", header_line)]

    mapped_cols = _map_header_aliases(raw_cols)

    results: List[Dict[str, Any]] = []
    for line in data_lines:
        stripped = line.strip()
        if not stripped:
            continue

        if delimiter:
            cells = stripped.split(delimiter)
        else:
            cells = re.split(r"\s{2,}", stripped)

        if len(cells) != len(mapped_cols):
            continue

        row_dict = {}
        for col_name, cell_val in zip(mapped_cols, cells):
            if col_name in REQUIRED_COLUMNS:
                row_dict[col_name] = _clean_cell(col_name, cell_val)

        if _is_valid_row(row_dict):
            results.append(row_dict)

    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

_HEADER_ALIASES: Dict[str, str] = {
    "txn_id": "transaction_id",
    "trans_id": "transaction_id",
    "tx_id": "transaction_id",
    "id": "transaction_id",
    "date": "timestamp",
    "datetime": "timestamp",
    "time": "timestamp",
    "txn_time": "timestamp",
    "store": "merchant",
    "merchant_name": "merchant",
    "category": "merchant_category",
    "cat": "merchant_category",
    "amt": "amount",
    "value": "amount",
    "card": "card_num",
    "card_number": "card_num",
    "device": "device_id",
    "dev_id": "device_id",
    "decline": "declined",
    "is_declined": "declined",
    "status": "declined",
}


def _map_header_aliases(header: List[str]) -> List[str]:
    """Map common header aliases to canonical column names."""
    return [_HEADER_ALIASES.get(h, h) for h in header]


def _clean_cell(col_name: str, value: Any) -> Any:
    """Type-coerce a cell value based on the target column."""
    if value is None:
        return None
    val_str = str(value).strip()
    if col_name == "amount":
        return _safe_float(val_str.replace("$", "").replace(",", ""))
    if col_name == "declined":
        lower = val_str.lower()
        if lower in ("1", "true", "yes", "declined"):
            return 1
        return 0
    return val_str


def _safe_float(s: str) -> float:
    """Convert string to float safely, defaulting to 0.0."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _is_valid_row(row: Dict[str, Any]) -> bool:
    """Check that a parsed row has all 8 required columns with non-empty values."""
    for col in REQUIRED_COLUMNS:
        if col not in row:
            return False
        val = row[col]
        if val is None or (isinstance(val, str) and not val.strip()):
            return False
    return True
