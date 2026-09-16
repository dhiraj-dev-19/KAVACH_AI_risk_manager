"""
schema_mapper.py — Centralized column mapping and placeholder logic for real-world bank statements.

Exposes:
    map_headers(raw_headers: List[str]) -> List[str]
    apply_placeholders(row_dict: Dict[str, Any]) -> Dict[str, Any]
"""

from typing import Any, Dict, List

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

_HEADER_ALIASES: Dict[str, str] = {
    # transaction_id
    "txn_id": "transaction_id",
    "trans_id": "transaction_id",
    "tx_id": "transaction_id",
    "id": "transaction_id",
    "tran_id": "transaction_id",
    "ref_no": "transaction_id",
    "reference": "transaction_id",
    "reference_number": "transaction_id",
    
    # timestamp
    "date": "timestamp",
    "datetime": "timestamp",
    "time": "timestamp",
    "txn_time": "timestamp",
    "value_date": "timestamp",
    "txn_date": "timestamp",
    "transaction_date": "timestamp",
    
    # merchant
    "store": "merchant",
    "merchant_name": "merchant",
    "description": "merchant",
    "narration": "merchant",
    "particulars": "merchant",
    "transaction_particulars": "merchant",
    "remarks": "merchant",
    "details": "merchant",
    
    # merchant_category
    "category": "merchant_category",
    "cat": "merchant_category",
    
    # amount
    "amt": "amount",
    "value": "amount",
    "dr": "amount",
    "cr": "amount",
    "debit": "amount",
    "credit": "amount",
    "withdrawal": "amount",
    "deposit": "amount",
    "withdrwal": "amount", # Common typo seen in India Post CSV
    
    # other
    "card": "card_num",
    "card_number": "card_num",
    "device": "device_id",
    "dev_id": "device_id",
    "decline": "declined",
    "is_declined": "declined",
    "status": "declined",
}

def map_headers(raw_headers: List[str]) -> List[str]:
    """Map common header aliases to canonical column names."""
    mapped = []
    for h in raw_headers:
        if not h:
            mapped.append("")
            continue
        cleaned_h = str(h).strip().lower().replace(" ", "_")
        mapped.append(_HEADER_ALIASES.get(cleaned_h, cleaned_h))
    return mapped

def apply_placeholders(row_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply explicit placeholders for structurally missing fields in real-world statements.
    Tracks injected fields in the `inferred_fields` list.
    """
    inferred_fields: List[str] = []
    
    # Ensure all required columns exist in the dictionary
    for col in REQUIRED_COLUMNS:
        if col not in row_dict:
            row_dict[col] = None

    # merchant_category
    category = row_dict.get("merchant_category")
    if not category or str(category).lower() in ("unknown", "none", "null", "n/a", "", "nan"):
        row_dict["merchant_category"] = "uncategorized"
        inferred_fields.append("merchant_category")

    # card_num
    card_num = row_dict.get("card_num")
    if not card_num or str(card_num).lower() in ("unknown", "none", "null", "n/a", "", "nan"):
        row_dict["card_num"] = "unknown"
        inferred_fields.append("card_num")

    # device_id
    device_id = row_dict.get("device_id")
    if not device_id or str(device_id).lower() in ("unknown", "none", "null", "n/a", "", "nan"):
        row_dict["device_id"] = "unknown"
        inferred_fields.append("device_id")

    # declined
    declined = row_dict.get("declined")
    if declined is None or str(declined).lower() in ("unknown", "none", "null", "n/a", "", "nan"):
        row_dict["declined"] = False
        inferred_fields.append("declined")
    else:
        # Convert existing truthy/falsy values cleanly
        lower = str(declined).lower()
        if lower in ("1", "true", "yes", "declined"):
            row_dict["declined"] = True
        else:
            row_dict["declined"] = False

    row_dict["inferred_fields"] = inferred_fields
    return row_dict
