import pytest
from fastapi.testclient import TestClient

# Must import from api_server to get the configured app
from src.api_server import app
from src.auth import create_access_token
from src.mongo_db import get_transactions_collection

client = TestClient(app)

@pytest.fixture
def auth_token():
    return create_access_token("test_user_statement_flow")

@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.fixture(autouse=True)
async def cleanup_db():
    """Clean up the test user's data after each test."""
    yield
    collection = get_transactions_collection()
    await collection.delete_many({"user_id": "test_user_statement_flow"})

def test_extract_requires_auth():
    response = client.post(
        "/statements/extract",
        files={"file": ("test.csv", b"dummy content", "text/csv")}
    )
    assert response.status_code == 401

def test_confirm_requires_auth():
    response = client.post("/statements/confirm", json=[{"some": "data"}])
    assert response.status_code == 401

def test_extract_csv_successful(auth_headers):
    # Create a realistic raw bank CSV with a preamble and non-standard columns
    csv_content = (
        "Bank Name: Example Bank\n"
        "Account Number: 123456789\n"
        "Statement Period: Jan 1 to Jan 31\n"
        "\n"
        "Txn Date, Description, Category, Withdrawal, Deposit\n"
        "2026-01-01 10:00:00, Coffee Shop, Food, 5.50, \n"
        "2026-01-02 12:00:00, Salary, Income, , 2000.00\n"
    ).encode("utf-8")

    response = client.post(
        "/statements/extract",
        headers=auth_headers,
        files={"file": ("statement.csv", csv_content, "text/csv")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "extracted"
    assert "mapped_schema" in data
    assert "preview_rows" in data
    assert "dropped_rows" in data
    
    rows = data["preview_rows"]
    assert len(rows) == 2
    
    # Check that aliasing worked
    assert rows[0]["merchant"] == "Coffee Shop"
    assert rows[0]["amount"] == 5.5
    assert rows[1]["merchant"] == "Salary"
    assert rows[1]["amount"] == 2000.0
    
    # Check that placeholders were applied correctly
    for row in rows:
        assert row["declined"] is False
        assert row["card_num"] == "unknown"
        assert row["device_id"] == "unknown"
        assert "inferred_fields" in row
        assert "declined" in row["inferred_fields"]
        assert "card_num" in row["inferred_fields"]

def test_extract_rejects_invalid_file(auth_headers):
    response = client.post(
        "/statements/extract",
        headers=auth_headers,
        files={"file": ("not_a_statement.txt", b"just some text", "text/plain")}
    )
    assert response.status_code == 400
    assert "Only .csv and .pdf" in response.json()["detail"]

def test_extract_drops_footer_rows(auth_headers):
    # Test CSV with a footer row that mimics a summary
    csv_content = (
        "Txn Date, Description, Category, Withdrawal, Deposit\n"
        "2026-01-01 10:00:00, Coffee Shop, Food, 5.50, \n"
        "241.88, Closing Balance, , , 21654.93\n"
    ).encode("utf-8")

    response = client.post(
        "/statements/extract",
        headers=auth_headers,
        files={"file": ("statement.csv", csv_content, "text/csv")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert len(data["preview_rows"]) == 1
    assert len(data["dropped_rows"]) == 1
    
    # The valid row should be the Coffee Shop
    assert data["preview_rows"][0]["merchant"] == "Coffee Shop"
    
    # The dropped row should be the Closing Balance
    dropped = data["dropped_rows"][0]
    assert dropped["timestamp"] == 241.88 or dropped["timestamp"] == "241.88"
    assert "Closing Balance" in dropped["merchant"]

def test_confirm_flow_successful(auth_headers):
    # Simulate a confirmed payload that was outputted from step 1
    preview_rows = [
        {
            "transaction_id": "txn-1",
            "timestamp": "2026-01-01 10:00:00",
            "merchant": "Coffee Shop",
            "merchant_category": "Food",
            "amount": 5.5,
            "card_num": "unknown",
            "device_id": "unknown",
            "declined": False,
            "inferred_fields": ["card_num", "device_id", "declined"]
        }
    ]

    response = client.post(
        "/statements/confirm",
        headers=auth_headers,
        json=preview_rows
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["rows_processed"] == 1
    assert data["rows_errored"] == 0
    assert "batch_id" in data
    
    # Verify results summary includes risk score and personal context
    summary = data["results_summary"][0]
    assert summary["transaction_id"] == "txn-1"
    assert "risk_score" in summary
    assert "personal_context" in summary
