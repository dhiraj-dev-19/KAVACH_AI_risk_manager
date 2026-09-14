"""
screenshot_parser.py — Extract transaction data from payment screenshots via Gemini vision.

Exposes:
    extract_transaction_from_screenshot(image_bytes: bytes) -> dict

Design:
    • Uses Gemini vision via the google-genai SDK (reusing the same client pattern
      and API key configuration from explain_api.py).
    • Requests structured JSON for the 8 raw columns:
        transaction_id, timestamp, merchant, merchant_category,
        amount, card_num, device_id, declined
    • Placeholder strategy for fields not visible in mobile/UPI/bank screenshots:
        - card_num  -> "unknown"
        - device_id -> "unknown"
        - declined  -> False
      Tracks all defaulted fields in "inferred_fields": list[str].
    • Retries once with a stricter prompt if output is invalid JSON or missing
      essential fields (amount, merchant).
    • Returns {"error": "extraction_failed"} on persistent failure.
"""

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

MODEL_NAME = "gemini-3.5-flash"


def _get_genai_client():
    """Create or retrieve Gemini client using the project's standard configuration."""
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
        print(f"[screenshot_parser] Gemini client init warning: {e}")
        return None


def _detect_mime_type(image_bytes: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    elif image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:12]:
        return "image/webp"
    elif image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _clean_json_text(text: str) -> str:
    """Strip markdown formatting or extraneous text to isolate raw JSON."""
    text = text.strip()
    # Match ```json ... ``` or ``` ... ```
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if code_block:
        return code_block.group(1).strip()
    # Match first { to last }
    brace_match = re.search(r"(\{[\s\S]*\})", text)
    if brace_match:
        return brace_match.group(1).strip()
    return text


def _call_gemini_vision(
    client, image_bytes: bytes, prompt: str, mime_type: str
) -> Optional[str]:
    """Invoke Gemini vision with prompt and image part, falling back to gemini-1.5-flash on error."""
    try:
        from google.genai import types
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[prompt, image_part],
            )
        except Exception as e:
            print(f"[screenshot_parser] Primary model {MODEL_NAME} failed ({e}), falling back to gemini-2.5-flash")
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, image_part],
            )

        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"[screenshot_parser] Gemini vision fallback error: {e}")
    return None


def _process_extraction_data(raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate required fields and apply explicit placeholder strategy."""
    # Check essential fields for fraud scoring
    merchant = raw_data.get("merchant")
    amount_raw = raw_data.get("amount")

    if not merchant or amount_raw is None:
        return None

    try:
        if isinstance(amount_raw, str):
            clean_amt = re.sub(r"[^\d.]", "", amount_raw)
            amount = float(clean_amt)
        else:
            amount = float(amount_raw)
    except (ValueError, TypeError):
        return None

    if amount <= 0:
        return None

    inferred_fields: List[str] = []

    # 1. card_num placeholder
    card_num = raw_data.get("card_num")
    if not card_num or str(card_num).lower() in ("unknown", "none", "null", "n/a", ""):
        card_num = "unknown"
        inferred_fields.append("card_num")
    else:
        card_num = str(card_num).strip()

    # 2. device_id placeholder
    device_id = raw_data.get("device_id")
    if not device_id or str(device_id).lower() in ("unknown", "none", "null", "n/a", ""):
        device_id = "unknown"
        inferred_fields.append("device_id")
    else:
        device_id = str(device_id).strip()

    # 3. declined placeholder (default False / 0)
    declined_val = raw_data.get("declined")
    if declined_val is None or str(declined_val).lower() in ("unknown", "none", "null", ""):
        declined = 0
        inferred_fields.append("declined")
    else:
        if isinstance(declined_val, bool):
            declined = 1 if declined_val else 0
        elif str(declined_val).lower() in ("true", "1", "declined", "failed"):
            declined = 1
        else:
            declined = 0

    # 4. transaction_id
    transaction_id = raw_data.get("transaction_id")
    if not transaction_id or str(transaction_id).lower() in ("unknown", "none", "null", ""):
        transaction_id = f"TXN-SCR-{uuid.uuid4().hex[:8].upper()}"
        inferred_fields.append("transaction_id")
    else:
        transaction_id = str(transaction_id).strip()

    # 5. timestamp
    timestamp = raw_data.get("timestamp")
    if not timestamp or str(timestamp).lower() in ("unknown", "none", "null", ""):
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        inferred_fields.append("timestamp")
    else:
        timestamp = str(timestamp).strip()

    # 6. merchant_category
    merchant_category = raw_data.get("merchant_category")
    if not merchant_category or str(merchant_category).lower() in ("unknown", "none", "null", ""):
        merchant_category = "misc_pos"
        inferred_fields.append("merchant_category")
    else:
        merchant_category = str(merchant_category).strip()

    return {
        "transaction_id": transaction_id,
        "timestamp": timestamp,
        "merchant": str(merchant).strip(),
        "merchant_category": merchant_category,
        "amount": amount,
        "card_num": card_num,
        "device_id": device_id,
        "declined": declined,
        "inferred_fields": inferred_fields,
    }


def extract_transaction_from_screenshot(image_bytes: bytes) -> Dict[str, Any]:
    """Extract transaction details from a payment/banking screenshot via Gemini vision.

    Returns:
        dict — transaction dict containing the 8 raw fields plus 'inferred_fields',
               OR {"error": "extraction_failed"} if unreadable or critical fields missing.
    """
    client = _get_genai_client()
    if not client:
        return {"error": "extraction_failed"}

    mime_type = _detect_mime_type(image_bytes)

    # Initial prompt
    primary_prompt = (
        "You are an automated transaction parser for a payment fraud system. "
        "Examine this payment/banking app screenshot (e.g. UPI, GPay, Paytm, credit card, net banking) "
        "and extract the transaction details into a single valid JSON object.\n\n"
        "Required JSON keys:\n"
        "- transaction_id: (string, e.g. UTR, Reference number, Txn ID, or null if absent)\n"
        "- timestamp: (string, formatted as YYYY-MM-DD HH:MM:SS if date/time visible, or null)\n"
        "- merchant: (string, the name of the merchant, recipient, store, or paid-to party)\n"
        "- merchant_category: (string, best matching category like shopping_net, grocery_pos, gas_transport, food_dining, misc_pos, or null)\n"
        "- amount: (number, the payment amount as float, without currency symbols)\n"
        "- card_num: (string, card number if visible, or null)\n"
        "- device_id: (string, device ID if visible, or null)\n"
        "- declined: (boolean, true if status was failed/declined, false if completed/successful, or null)\n\n"
        "Return ONLY the raw JSON object, without markdown formatting, backticks, or commentary."
    )

    response_text = _call_gemini_vision(client, image_bytes, primary_prompt, mime_type)

    if response_text:
        try:
            parsed = json.loads(_clean_json_text(response_text))
            processed = _process_extraction_data(parsed)
            if processed is not None:
                return processed
        except Exception:
            pass

    # Retry once with a stricter prompt if first attempt failed
    retry_prompt = (
        "STRICT EXTRACTION RETRY: The previous attempt failed to extract a valid merchant and amount. "
        "Please carefully read this image. Identify the transaction AMOUNT (number) and the MERCHANT/RECIPIENT name. "
        "Output ONLY a JSON object with these keys:\n"
        '{"merchant": "name", "amount": 0.0, "transaction_id": null, "timestamp": null, '
        '"merchant_category": null, "card_num": null, "device_id": null, "declined": false}\n'
        "Do not include any other text or markdown code fences."
    )

    retry_response_text = _call_gemini_vision(client, image_bytes, retry_prompt, mime_type)

    if retry_response_text:
        try:
            parsed = json.loads(_clean_json_text(retry_response_text))
            processed = _process_extraction_data(parsed)
            if processed is not None:
                return processed
        except Exception:
            pass

    return {"error": "extraction_failed"}
