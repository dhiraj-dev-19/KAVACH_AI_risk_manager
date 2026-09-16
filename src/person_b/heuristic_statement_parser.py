"""
heuristic_statement_parser.py — Parse real-world bank statements (CSV/PDF).

Detects headers, skips preamble, maps columns via schema_mapper, and cleans data.
"""

import io
import re
from typing import Any, Dict, List, Union

import pandas as pd
import pdfplumber

from src.person_b.schema_mapper import REQUIRED_COLUMNS, apply_placeholders, map_headers


def extract_transactions_from_csv(file_bytes: bytes) -> Dict[str, Any]:
    """Extract transactions from a raw bank statement CSV."""
    try:
        decoded = file_bytes.decode('utf-8', errors='replace')
        lines = decoded.splitlines()
        
        header_idx = -1
        mapped_header = []
        
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            cells = line.split(',')
            cleaned_cells = [c.strip().lower().replace(" ", "_") for c in cells]
            potential_mapping = map_headers(cleaned_cells)
            
            matches = sum(1 for col in REQUIRED_COLUMNS if col in potential_mapping)
            if matches >= 3:
                header_idx = i
                mapped_header = potential_mapping
                break
                
        if header_idx == -1:
            return {"error": "no_transactions_parsed", "message": "Could not locate a valid transaction table header in the CSV."}
            
        df = pd.read_csv(io.StringIO(decoded), skiprows=header_idx)
        df.columns = map_headers(list(df.columns))
        
        valid_rows, dropped_rows = _extract_rows_from_dataframe(df)
        return {"valid_rows": valid_rows, "dropped_rows": dropped_rows}

    except Exception as e:
        return {"error": "extraction_failed", "message": str(e)}


def extract_transactions_from_pdf(file_bytes: bytes) -> Dict[str, Any]:
    """Extract transactions from a text-based PDF bank statement using table extraction."""
    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
    except Exception:
        return {"error": "scanned_pdf_not_supported"}

    all_valid_results = []
    all_dropped_results = []
    
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if not table or len(table) < 2:
                continue
                
            raw_header = [str(h) if h else "" for h in table[0]]
            mapped_header = map_headers(raw_header)
            
            matches = sum(1 for col in REQUIRED_COLUMNS if col in mapped_header)
            if matches >= 3:
                df = pd.DataFrame(table[1:], columns=mapped_header)
                valid_rows, dropped_rows = _extract_rows_from_dataframe(df)
                all_valid_results.extend(valid_rows)
                all_dropped_results.extend(dropped_rows)
                
    pdf.close()
    
    if not all_valid_results and not all_dropped_results:
        return {"error": "no_transactions_parsed", "message": "Could not parse any transactions from this PDF."}
        
    return {"valid_rows": all_valid_results, "dropped_rows": all_dropped_results}


def _is_plausible_transaction(row_dict: Dict[str, Any]) -> bool:
    """Check if a row is a plausible transaction, rejecting misaligned footers."""
    timestamp = str(row_dict.get("timestamp", ""))
    merchant = str(row_dict.get("merchant", ""))
    txn_id = str(row_dict.get("transaction_id", ""))

    # 1. Timestamp must resemble a date (contain letters for months, or separators -/)
    if not (re.search(r'[a-zA-Z]', timestamp) or '/' in timestamp or '-' in timestamp):
        return False
    # Must contain at least one digit
    if not any(char.isdigit() for char in timestamp):
        return False

    # 2. Merchant should not be entirely numeric or a float (e.g. "21542.00")
    if re.match(r"^\d+(\.\d+)?$", merchant.strip()):
        return False

    # 3. Transaction ID should not have a decimal fraction (e.g. "21654.93")
    if txn_id and '.' in txn_id:
        # Check if the part after the decimal is just numbers (indicating a float)
        if re.match(r"^\d+\.\d+$", txn_id.strip()):
            return False

    return True


def _extract_rows_from_dataframe(df: pd.DataFrame) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Convert a dataframe with mapped columns into normalized dictionaries."""
    valid_results = []
    dropped_results = []
    
    for _, row in df.iterrows():
        row_dict = {}
        for col_name, val in zip(df.columns, row.values):
            if col_name in REQUIRED_COLUMNS:
                if pd.isna(val) or val == "":
                    continue
                    
                if col_name == "amount" and "amount" in row_dict:
                    pass
                else:
                    row_dict[col_name] = _clean_cell(col_name, val)
                
                if col_name == "amount":
                    clean_val = _clean_cell(col_name, val)
                    if clean_val > 0:
                        row_dict["amount"] = clean_val
                        
        if row_dict.get("amount") and row_dict.get("timestamp"):
            if _is_plausible_transaction(row_dict):
                final_row = apply_placeholders(row_dict)
                valid_results.append(final_row)
            else:
                dropped_results.append(row_dict)
            
    return valid_results, dropped_results


def _clean_cell(col_name: str, value: Any) -> Any:
    """Type-coerce a cell value based on the target column."""
    if value is None:
        return None
    val_str = str(value).strip()
    
    if col_name == "amount":
        # Remove currency symbols and commas
        clean_str = re.sub(r"[^\d.]", "", val_str)
        try:
            return float(clean_str) if clean_str else 0.0
        except ValueError:
            return 0.0
            
    if col_name == "declined":
        lower = val_str.lower()
        if lower in ("1", "true", "yes", "declined"):
            return True
        return False
        
    return val_str
