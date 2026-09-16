# AI Risk Manager — Fraud-Spike Detector

**Razorpay Buildathon Track 02 Submission**

An end-to-end real-time transaction fraud-spike detection, cost trade-off analysis, and generative explainability engine.

---

## 🎯 Architecture Pattern

`ingest` → `inject` → `feature engineer` → `train` → `threshold-analyze` → `cohort-compare` → `decide` → `explain` → `serve`

```
 ┌─────────────────────────┐
 │ Synthetic Transaction │
 │ Stream Generator       │
 └───────────┬─────────────┘
             │ (simulates live feed)
             ▼
 ┌─────────────────────────┐
 │ Feature Engineering     │
 │ (rolling windows, 5m/1h)│
 └───────────┬─────────────┘
 ┌───────────┴─────────────┐
 ▼                         ▼
 ┌───────────────────┐ ┌───────────────────────┐
 │ Supervised Model  │ │ In-Memory Cohort      │
 │ (XGBoost/GBDT)    │ │ Engine (<1ms)         │
 └───────────┬───────┘ └───────────┬───────────┘
             └────────────┬────────┘
                          ▼
             ┌─────────────────────────┐
             │ Decision Engine         │
             │ (Defense-only mapping)  │
             └───────────┬─────────────┘
                         ▼
             ┌─────────────────────────┐
             │ Gemini Explanation Layer│
             │ (1-2 sentence audit)    │
             └───────────┬─────────────┘
                         ▼
             ┌─────────────────────────┐
             │ Frontend Dashboard      │
             │ (React + Vite, live feed)│
             └─────────────────────────┘
```

---

## 🛡️ Hackathon Safety Guardrail

This system is **strictly defense-only**. The decision engine action set is constrained to:
- `allow`: Clear transaction automatically.
- `flag_for_review`: Flag for internal analyst review.
- `hold_for_verification`: Request secondary step-up verification.
- `auto_decline`: Automated decline with plain-language audit reason.

**Zero outbound automated actions or external party retaliation are included.**

---

## 🏦 Dynamic Statement Upload Pipeline

The system includes a robust data ingestion pipeline designed for real-world user uploads, capable of handling messy, unstructured bank statements:

- **Heuristic CSV Parsing**: Dynamically detects the start of transaction tables, skips headers/preambles, drops summary/footer rows, and normalizes column headers using a centralized schema mapper.
- **PDF Extraction**: Extracts transaction grids from text-based bank statement PDFs automatically.
- **Image/Screenshot Fallback (OCR)**: For non-text PDFs and screenshots, falls back to a Gemini-powered Vision extraction layer to cleanly parse transactions into the normalized schema.
- **2-Step "Extract & Confirm" API**: Separates extraction (`/statements/extract`) from scoring/persistence (`/statements/confirm`) to allow UI previews, user corrections, and transparent reporting of dropped footer rows.

---

## ⚡ Quick Start

### 1. Requirements Setup
```bash
pip install -r requirements.txt
```

### 2. Run Data Pipeline & Train Model
```bash
python src/person_a/clean_data.py
python src/person_a/inject_fraud_spikes.py
python src/person_a/train.py
python src/person_a/threshold_analysis.py
```

### 3. Run FastAPI Backend REST Server
```bash
python src/api_server.py
# Server runs on http://127.0.0.1:8000
```

### 4. Run Stream Simulator (Optional Standalone)
```bash
python src/person_a/simulate_live_stream.py
```

### 5. Run React Frontend
```bash
cd frontend
npm install
npm run dev
# Dashboard opens on http://localhost:5173
```

---

## 🧪 Unit Tests

```bash
pytest tests/
```
