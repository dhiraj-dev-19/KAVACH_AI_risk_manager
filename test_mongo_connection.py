"""
test_mongo_connection.py — Phase 0 Atlas connectivity test (throwaway script).

Usage:
    1. Fill in MONGO_URI in .env
    2. Run: python test_mongo_connection.py

What it does:
    - Connects to Atlas via Motor (async)
    - Writes a test document to `judge_db._connection_test`
    - Reads it back and prints it
    - Deletes the test document
    - Prints PASS / FAIL with timing info

Do NOT import this into production code.
"""

import asyncio
import os
import sys
import time

# Resolve project root so python-dotenv finds .env regardless of CWD
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))


async def run_connection_test():
    mongo_uri = os.getenv("MONGO_URI", "")
    if not mongo_uri or mongo_uri.startswith("<"):
        print("\n[FAIL] MONGO_URI is not set in .env — edit the file and fill in your Atlas connection string.\n")
        sys.exit(1)

    print(f"\n[test_mongo] Connecting to Atlas...")

    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError:
        print("[FAIL] motor is not installed. Run: pip install motor>=3.3")
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=10_000)
    db = client["judge_db"]
    collection = db["_connection_test"]

    # ── Write ────────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    test_doc = {
        "test": True,
        "message": "JUDGE Phase-0 connection test",
        "ts": time.time(),
    }

    try:
        insert_result = await collection.insert_one(test_doc)
        inserted_id = insert_result.inserted_id
        write_ms = round((time.perf_counter() - t0) * 1000, 1)
        print(f"[test_mongo] ✓ Write OK   — inserted_id={inserted_id}  ({write_ms} ms)")
    except Exception as exc:
        print(f"[FAIL] Write failed: {exc}")
        client.close()
        sys.exit(1)

    # ── Read ─────────────────────────────────────────────────────────────────
    t1 = time.perf_counter()
    try:
        found = await collection.find_one({"_id": inserted_id})
        read_ms = round((time.perf_counter() - t1) * 1000, 1)
        if found:
            # Convert ObjectId to str for clean printing
            found["_id"] = str(found["_id"])
            import json
            print(f"[test_mongo] ✓ Read  OK   — document returned ({read_ms} ms):")
            print("             ", json.dumps(found, indent=2))
        else:
            print(f"[FAIL] Read returned None — document not found after insert.")
            client.close()
            sys.exit(1)
    except Exception as exc:
        print(f"[FAIL] Read failed: {exc}")
        client.close()
        sys.exit(1)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    try:
        await collection.delete_one({"_id": inserted_id})
        print(f"[test_mongo] ✓ Cleanup OK — test document deleted")
    except Exception as exc:
        print(f"[WARN] Cleanup failed (non-fatal): {exc}")

    client.close()

    total_ms = round((time.perf_counter() - t0) * 1000, 1)
    print(f"\n[PASS] Atlas connection verified — total round-trip {total_ms} ms")
    print("[PASS] You may now proceed to Phase 1 (JWT Auth).\n")


if __name__ == "__main__":
    asyncio.run(run_connection_test())
