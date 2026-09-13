"""
api_server.py - Production REST API Server for AI Risk Manager (Fraud-Spike Detector).

Endpoints:
    GET  /                     - Welcome & API service status
    GET  /transactions/live    - Recent scored transactions with decision-engine outputs
    GET  /transactions/{id}    - Single transaction detail with Gemini explanation
    GET  /threshold-curve      - Precision/Recall/Cost trade-off data for threshold slider
    GET  /api/health           - Server health check
    POST /simulation/seed      - Pre-populate database with seed transactions for immediate demo view
"""

import os
import sys
import json
import time
import asyncio
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()  # loads .env from project root

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.db import get_live_transactions, get_transaction_by_id, save_scored_transaction, load_history_from_csv
from src.person_a.simulate_live_stream import process_single_event

# New routers (Phase 1 & 2)
from src.routers.auth_router import router as auth_router
from src.routers.transactions_router import router as transactions_router
from src import mongo_db

THRESHOLD_JSON = os.path.join(_PROJECT_ROOT, "data", "models", "threshold_analysis.json")
INJECTED_CSV = os.path.join(_PROJECT_ROOT, "data", "processed", "injected_transactions.csv")


def seed_initial_demo_data():
    """Seed initial transactions if database is empty."""
    txns = get_live_transactions(limit=5)
    if not txns and os.path.exists(INJECTED_CSV):
        import pandas as pd
        print("[api_server] Database is empty. Pre-seeding 30 transactions from demo dataset...")
        df = pd.read_csv(INJECTED_CSV).head(35)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        recent = []
        for idx, row in df.iterrows():
            txn = row.to_dict()
            process_single_event(txn, recent)
            recent.append(txn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for FastAPI startup and shutdown."""
    try:
        # Pre-populate transaction_history with full processed dataset so that
        # get_recent_history_for_scoring() can return real context for live scoring.
        if os.path.exists(INJECTED_CSV):
            load_history_from_csv(INJECTED_CSV)
        seed_initial_demo_data()
    except Exception as e:
        print(f"[api_server] Startup seed warning: {e}")

    # Initialise Motor client (validates MONGO_URI is set)
    try:
        mongo_db.get_client()
        print("[api_server] Motor/MongoDB client initialised.")
    except Exception as e:
        print(f"[api_server] MongoDB init warning (non-fatal): {e}")

    yield

    # Graceful Motor shutdown
    mongo_db.close_client()
    print("[api_server] Motor/MongoDB client closed.")


app = FastAPI(
    title="AI Risk Manager API - Fraud-Spike Detector",
    description="REST API serving live transaction risk scoring, cost trade-off curves, and Gemini explainability.",
    version="2.0.0",
    lifespan=lifespan
)

# Enable CORS for React/Vite development & production frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ──────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(transactions_router)


@app.get("/")
def root_status():
    """Root endpoint welcoming API consumers."""
    return {
        "service": "AI Risk Manager API - Fraud-Spike Detector",
        "status": "online",
        "documentation": "/docs",
        "health": "/api/health",
        "endpoints": [
            "/transactions/live",
            "/transactions/{id}",
            "/threshold-curve"
        ]
    }


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "AI Risk Manager (Fraud-Spike Detector)",
        "timestamp": time.time(),
        "database": "SQLite WAL mode connected"
    }


@app.get("/transactions/live")
def get_live_stream(limit: int = 50):
    """Return recent scored transactions with decision engine outputs."""
    txns = get_live_transactions(limit=limit)
    if not txns:
        seed_initial_demo_data()
        txns = get_live_transactions(limit=limit)
    return {
        "count": len(txns),
        "transactions": txns
    }


@app.get("/transactions/{transaction_id}")
def get_transaction_detail(transaction_id: str):
    """Return single transaction detail including Gemini natural language explanation."""
    txn = get_transaction_by_id(transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")
    return txn


@app.get("/threshold-curve")
def get_threshold_curve():
    """Return precision/recall/false-positive cost trade-off data for interactive slider."""
    if os.path.exists(THRESHOLD_JSON):
        try:
            with open(THRESHOLD_JSON, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[api_server] Error reading threshold_analysis.json: {e}")

    # Fallback response if threshold script hasn't run yet
    return {
        "optimal_threshold": 0.35,
        "recommended_bands": {
            "low": {"max": 0.35, "action": "allow"},
            "medium": {"min": 0.35, "max": 0.60, "action": "flag_for_review"},
            "high": {"min": 0.60, "max": 0.85, "action": "hold_for_verification"},
            "very_high": {"min": 0.85, "max": 1.00, "action": "auto_decline"}
        },
        "threshold_curve": [
            {"threshold": 0.15, "precision": 0.62, "recall": 0.98, "f1_score": 0.76, "estimated_fp_cost": 4200.0, "estimated_fraud_caught": 18500.0},
            {"threshold": 0.35, "precision": 0.88, "recall": 0.92, "f1_score": 0.90, "estimated_fp_cost": 1150.0, "estimated_fraud_caught": 17200.0},
            {"threshold": 0.60, "precision": 0.95, "recall": 0.78, "f1_score": 0.86, "estimated_fp_cost": 320.0, "estimated_fraud_caught": 14500.0},
            {"threshold": 0.85, "precision": 0.98, "recall": 0.45, "f1_score": 0.62, "estimated_fp_cost": 80.0, "estimated_fraud_caught": 8200.0}
        ]
    }


@app.post("/simulation/seed")
def trigger_seed_simulation(background_tasks: BackgroundTasks):
    """Trigger background generation of additional simulated transaction events."""
    def _run_batch():
        if os.path.exists(INJECTED_CSV):
            import pandas as pd
            df = pd.read_csv(INJECTED_CSV).sample(n=10)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            for idx, row in df.iterrows():
                process_single_event(row.to_dict())
                time.sleep(0.3)

    background_tasks.add_task(_run_batch)
    return {"message": "Simulation batch triggered in background."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
