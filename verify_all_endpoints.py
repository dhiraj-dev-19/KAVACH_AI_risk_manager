"""
verify_all_endpoints.py — End-to-end verification script for JUDGE API.
Tests:
1. Existing endpoints (/api/health, /threshold-curve, /transactions/live)
2. Auth endpoints (/auth/signup, /auth/login, /auth/me)
3. CSV upload endpoint (/transactions/upload-csv)
4. MongoDB Atlas persistence verification
"""

import io
import os
import sys
import time
import uuid
import asyncio
import requests

BASE_URL = "http://127.0.0.1:8000"

def test_endpoint(name, func):
    print(f"\n[TEST] {name}...")
    try:
        func()
        print(f"[PASS] {name}")
        return True
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        return False

def main():
    results = []

    # 1. Health check
    def check_health():
        r = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("status") == "healthy", f"Unexpected payload: {data}"
    results.append(test_endpoint("1. GET /api/health", check_health))

    # 2. Existing route: /threshold-curve
    def check_threshold():
        r = requests.get(f"{BASE_URL}/threshold-curve", timeout=10)
        assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
        data = r.json()
        assert "optimal_threshold" in data, f"Missing optimal_threshold: {data}"
    results.append(test_endpoint("2. GET /threshold-curve (existing route)", check_threshold))

    # 3. Existing route: /transactions/live
    def check_live():
        r = requests.get(f"{BASE_URL}/transactions/live?limit=5", timeout=10)
        assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
        data = r.json()
        assert "transactions" in data, f"Missing transactions: {data}"
    results.append(test_endpoint("3. GET /transactions/live (existing route)", check_live))

    # 4. Auth: Signup
    unique_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    password = "SuperSecretPassword123!"
    auth_token = None

    def check_signup():
        nonlocal auth_token
        payload = {"email": unique_email, "password": password}
        r = requests.post(f"{BASE_URL}/auth/signup", json=payload, timeout=10)
        assert r.status_code == 201, f"Status {r.status_code}: {r.text}"
        data = r.json()
        assert "access_token" in data, f"Missing access_token: {data}"
        auth_token = data["access_token"]
    results.append(test_endpoint("4. POST /auth/signup (new user)", check_signup))

    # 5. Auth: Duplicate Signup (409 Conflict)
    def check_duplicate_signup():
        payload = {"email": unique_email, "password": password}
        r = requests.post(f"{BASE_URL}/auth/signup", json=payload, timeout=10)
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
    results.append(test_endpoint("5. POST /auth/signup (duplicate rejection 409)", check_duplicate_signup))

    # 6. Auth: Login success
    def check_login():
        payload = {"email": unique_email, "password": password}
        r = requests.post(f"{BASE_URL}/auth/login", json=payload, timeout=10)
        assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
        data = r.json()
        assert "access_token" in data, f"Missing access_token: {data}"
    results.append(test_endpoint("6. POST /auth/login (valid credentials)", check_login))

    # 7. Auth: Login failure (401)
    def check_login_failure():
        payload = {"email": unique_email, "password": "WrongPassword!"}
        r = requests.post(f"{BASE_URL}/auth/login", json=payload, timeout=10)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
    results.append(test_endpoint("7. POST /auth/login (invalid password 401)", check_login_failure))

    # 8. Auth: GET /auth/me unauthenticated (401)
    def check_me_unauthenticated():
        r = requests.get(f"{BASE_URL}/auth/me", timeout=10)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
    results.append(test_endpoint("8. GET /auth/me (unauthenticated 401)", check_me_unauthenticated))

    # 9. Auth: GET /auth/me authenticated
    user_id_from_me = None
    def check_me_authenticated():
        nonlocal user_id_from_me
        headers = {"Authorization": f"Bearer {auth_token}"}
        r = requests.get(f"{BASE_URL}/auth/me", headers=headers, timeout=10)
        assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
        data = r.json()
        assert "user_id" in data, f"Missing user_id: {data}"
        user_id_from_me = data["user_id"]
    results.append(test_endpoint("9. GET /auth/me (authenticated 200)", check_me_authenticated))

    # 10. CSV Upload: Unauthenticated (401)
    def check_upload_unauth():
        files = {"file": ("test.csv", io.BytesIO(b"a,b,c\n1,2,3"), "text/csv")}
        r = requests.post(f"{BASE_URL}/transactions/upload-csv", files=files, timeout=10)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
    results.append(test_endpoint("10. POST /transactions/upload-csv (unauthenticated 401)", check_upload_unauth))

    # 11. CSV Upload: Column mismatch (422)
    def check_upload_mismatch():
        headers = {"Authorization": f"Bearer {auth_token}"}
        bad_csv = "transaction_id,amount,invalid_col\nTXN-001,10.5,foo\n"
        files = {"file": ("bad.csv", io.BytesIO(bad_csv.encode("utf-8")), "text/csv")}
        r = requests.post(f"{BASE_URL}/transactions/upload-csv", headers=headers, files=files, timeout=10)
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
        data = r.json()
        detail = data.get("detail", {})
        assert detail.get("error") == "column_mismatch", f"Unexpected error key: {detail}"
        assert "missing_columns" in detail, f"Missing missing_columns in detail: {detail}"
        print(f"       Column diff detail returned: {detail['missing_columns']}")
    results.append(test_endpoint("11. POST /transactions/upload-csv (column mismatch 422)", check_upload_mismatch))

    # 12. CSV Upload: Valid CSV scoring & persistence (200)
    batch_id = None
    def check_upload_valid():
        nonlocal batch_id
        headers = {"Authorization": f"Bearer {auth_token}"}
        valid_csv = (
            "transaction_id,timestamp,merchant,merchant_category,amount,card_num,device_id,declined\n"
            "TXN-VERIFY-001,2026-01-01 00:00:37,fraud_Kihn_Inc,grocery_pos,12.7,4532_6228_9097,DEV_86370,0\n"
            "TXN-VERIFY-002,2026-01-01 00:02:06,fraud_Bednar_Inc,shopping_net,77.96,4532_1510_3368,DEV_75301,0\n"
            "TXN-VERIFY-003,2026-01-01 00:03:29,fraud_Gould_Group,shopping_net,845.21,4532_7798_6552,DEV_98607,0\n"
        )
        files = {"file": ("valid_transactions.csv", io.BytesIO(valid_csv.encode("utf-8")), "text/csv")}
        r = requests.post(f"{BASE_URL}/transactions/upload-csv", headers=headers, files=files, timeout=30)
        assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("rows_processed") == 3, f"Expected 3 rows processed, got {data}"
        assert data.get("rows_errored") == 0, f"Expected 0 errors, got {data}"
        batch_id = data.get("upload_batch_id")
        assert batch_id, f"Missing upload_batch_id: {data}"
        print(f"       Batch ID: {batch_id}, Scored summary: {data.get('results_summary')}")
    results.append(test_endpoint("12. POST /transactions/upload-csv (valid scoring & Mongo persist)", check_upload_valid))

    # 13. Direct MongoDB Atlas verification
    async def check_mongo_direct():
        from dotenv import load_dotenv
        load_dotenv()
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_uri = os.getenv("MONGO_URI")
        client = AsyncIOMotorClient(mongo_uri)
        db = client["judge_db"]
        
        # Verify user exists
        user_doc = await db["users"].find_one({"email": unique_email})
        assert user_doc is not None, f"User {unique_email} not found in Atlas 'users' collection!"
        assert "hashed_password" in user_doc
        print(f"       Verified user document in Atlas: _id={user_doc['_id']}, email={user_doc['email']}")

        # Verify transactions exist
        cursor = db["transactions"].find({"upload_batch_id": batch_id})
        docs = await cursor.to_list(length=10)
        assert len(docs) == 3, f"Expected 3 transactions in Atlas for batch {batch_id}, got {len(docs)}"
        for d in docs:
            assert d.get("user_id") == user_id_from_me
            assert "risk_score" in d
            print(f"       Atlas Txn: id={d.get('transaction_id')}, score={d.get('risk_score')}, user={d.get('user_id')}")
        
        # Cleanup test records
        await db["users"].delete_one({"_id": user_doc["_id"]})
        await db["transactions"].delete_many({"upload_batch_id": batch_id})
        print("       Cleaned up test user and test transactions from Atlas.")
        client.close()

    def run_mongo_check():
        asyncio.run(check_mongo_direct())

    results.append(test_endpoint("13. Direct Atlas MongoDB verification (user & transaction docs)", run_mongo_check))

    # Summary
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n==========================================")
    print(f"VERIFICATION SUMMARY: {passed}/{total} PASSED")
    print(f"==========================================")
    if passed != total:
        sys.exit(1)

if __name__ == "__main__":
    main()
