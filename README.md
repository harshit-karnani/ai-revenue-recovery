<div align="center">

# RevGuard
### Failure-Aware Revenue Recovery Engine

**Razorpay AI Revenue Recovery Buildathon — Submission**

An intelligent, regulatory-first recurring-payment recovery platform that safely maximises revenue recovery while enforcing strict RBI and NPCI compliance invariants at every step of the pipeline.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](#11-setup--running-locally)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](#2-system-architecture)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-4169E1?logo=postgresql&logoColor=white)](#11-setup--running-locally)
[![Tests](https://img.shields.io/badge/Tests-45%2F45%20passing-brightgreen)](#12-running-tests)
[![License](https://img.shields.io/badge/Status-Hackathon%20Submission-informational)](#)

</div>

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [Decision Pipeline (7 Stages)](#3-decision-pipeline-7-stages)
4. [Fail-Closed Protocol](#4-fail-closed-protocol)
5. [API Reference](#5-api-reference)
6. [Safety Validator — 13 Invariants](#6-safety-validator--13-invariants)
7. [Machine Learning Classifier](#7-machine-learning-classifier)
8. [LLM Reasoning Layer](#8-llm-reasoning-layer)
9. [Idempotency & Concurrency](#9-idempotency--concurrency)
10. [Project Structure](#10-project-structure)
11. [Setup & Running Locally](#11-setup--running-locally)
12. [Running Tests](#12-running-tests)
13. [Security Scorecard](#13-security-scorecard)
14. [Known Limitations & Future Work](#14-known-limitations--future-work)

---

## 1. Overview

Traditional retry systems re-execute failed recurring payments blindly — risking regulatory violations under RBI/NPCI mandates, double-charges, and eroded customer trust. **RevGuard** replaces blind retries with a deterministic, auditable decision pipeline that only ever calls a payment gateway once a transaction has cleared every regulatory, statistical, and safety gate.

RevGuard enforces a strict hierarchy of trust, from certainty to inference:

```
Regulatory Rules → ML Classifier → LLM Reasoning → Strategy Router
   → Persisted Decision → Safety Validator → Idempotency Reservation
      → Gateway Simulator → Performance Feedback
```

**Key guarantees**

| Guarantee | Description |
|---|---|
| **Zero unsafe gateway calls** | No gateway call is ever made for a Bucket C (regulatory) decision |
| **Zero duplicate executions** | Enforced under any level of concurrency, via atomic DB reservation |
| **Zero silent fallbacks** | An unavailable LLM fails *closed*, never open |
| **13 independent safety checks** | Run before every single execution, with no exceptions |

---

## 2. System Architecture

RevGuard is built around four layered abstractions, each with a single, well-defined responsibility:

| Layer | Role | Principle |
|---|---|---|
| **Regulatory Rules Engine** | Deterministic RBI/NPCI compliance | Rules = Certainty |
| **ML Classifier** | Classifies ambiguous decline codes | ML = Learned Ambiguity |
| **LLM Reasoning** | Semantic disambiguation for low-confidence ML | LLM = Unresolved Reasoning |
| **Execution & Safety Firewall** | Atomic, idempotent, validated gateway calls | Execution = Controlled Side Effects |

### Decline Code → Bucket Classification

| Bucket | Meaning | Recovery Action |
|:---:|---|---|
| **A** | Customer-side failure (insufficient funds, expired card) | Smart retry via payment link / card-update request |
| **B** | Bank / network ambiguity (generic decline, timeout) | Intelligent retry with adaptive backoff |
| **C** | Regulatory / mandate issue (pre-debit missed, AFA exceeded) | **Blocked** — no gateway call, escalated to customer |
| **Terminal** | Retry cap (≥ 4 attempts) exceeded | Permanently failed — no further action |

---

## 3. Decision Pipeline (7 Stages)

```
┌──────────────────────────────────────────────────────────────┐
│  Stage 1 │ REGULATORY ENGINE  │ RBI/NPCI deterministic rules  │
│  Stage 2 │ RULES TAXONOMY     │ Decline code classification   │
│  Stage 3 │ ML CLASSIFIER      │ LogisticRegression (≥ 0.75)   │
│  Stage 4 │ LLM REASONING      │ Gemini / Claude (< 0.75)      │
│  Stage 5 │ STRATEGY ROUTER    │ Adaptive strategy selection   │
│  Stage 6 │ SAFETY FIREWALL    │ 13-invariant validator        │
│  Stage 7 │ GATEWAY EXECUTION  │ Atomic idempotent execution   │
└──────────────────────────────────────────────────────────────┘
```

The pipeline is fully **two-phase decoupled**, separating decision-making from side effects:

- **`POST /evaluate`** — runs Stages 1–5, persists an authoritative `RecoveryDecisionRecord`, and returns a `decision_id`. **No side effects.**
- **`POST /execute`** — runs Stages 6–7, requires a valid `decision_id` and `idempotency_key`. All 13 safety checks run before any gateway interaction.

---

## 4. Fail-Closed Protocol

When ML confidence falls below the `0.75` threshold, the event is escalated to the LLM. If the LLM is unavailable — timeout, API error, or invalid output — the system **does not fall back to the raw ML prediction**. Instead, it enforces a strict unresolved state:

```
bucket          = None
strategy_id     = None
requires_llm    = True
next_action     = "llm_unavailable"
```

Any subsequent call to `/execute` against this decision is rejected with **`HTTP 403 SAFETY_UNRESOLVED_STATE`**.

**Why this matters:** the `0.75` confidence threshold is the explicit boundary below which a prediction is deemed insufficient for autonomous financial execution. Silently reusing a rejected prediction after LLM failure would quietly convert an insufficient signal into an executable decision — a safety violation by design, not an edge case to patch around.

---

## 5. API Reference

### `POST /api/v1/recovery/evaluate`

Evaluates a payment-failure event through the full decision pipeline. Persists the authoritative decision and returns a `decision_id` for later execution. **Never touches a payment gateway.**

**Request**

```json
{
  "transaction_id": "txn_001",
  "event": {
    "amount": 1200.00,
    "currency": "INR",
    "payment_type": "card",
    "subscription_category": "ecommerce_subscription",
    "decline_code": "insufficient_funds",
    "attempt_count": 1,
    "mandate_status": "active",
    "authentication_status": "not_authenticated",
    "notification_sent_at": "2026-08-30T13:00:00+05:30",
    "scheduled_at": "2026-08-31T14:00:00+05:30",
    "current_time": "2026-08-31T14:00:00+05:30"
  }
}
```

**Response — `200 OK`**

```json
{
  "decision_id": "uuid",
  "bucket": "A",
  "classified_by": "rules",
  "confidence": 1.0,
  "strategy": "send_payment_link",
  "requires_llm": false,
  "next_action": "retry",
  "reasoning": null
}
```

### `POST /api/v1/recovery/execute`

Executes a previously evaluated decision. Loads the **persisted** decision from the database — client-supplied decision data is ignored. Runs all 13 safety invariants before any gateway interaction.

**Request**

```json
{
  "decision_id": "uuid-from-evaluate",
  "transaction_id": "txn_001",
  "idempotency_key": "idemp_txn_001_unique_key"
}
```

**Responses**

| HTTP | Meaning |
|:---:|---|
| `200 OK` | Executed successfully, or idempotent replay of a prior execution |
| `403 Forbidden` | A safety invariant was violated — gateway was **not** called |
| `404 Not Found` | `decision_id` does not exist in the database |
| `409 Conflict` | Concurrent duplicate request with the same `idempotency_key` |
| `422 Unprocessable Entity` | Missing or invalid fields |

### Supporting Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Database connectivity status |
| `GET /api/v1/system-status` | LLM provider, model name, ML model state, confidence threshold |
| `GET /api/v1/dashboard/batch-summary` | Aggregated revenue-recovery metrics from the demo batch |
| `POST /api/v1/dashboard/run-batch` | Triggers the 150-transaction simulated recovery batch (`MockProvider`, no live quota consumed) |

---

## 6. Safety Validator — 13 Invariants

Every `/execute` call passes through all 13 invariants **before** the atomic idempotency reservation and **before** any gateway call is made:

| # | Invariant | Condition Blocked |
|:---:|---|---|
| 1 | `SAFETY_RETRY_CAP_EXCEEDED` | `attempt_count >= 4` |
| 2 | `SAFETY_BUCKET_C_FORBIDDEN` | Decision bucket is `C` |
| 3 | `SAFETY_UNRESOLVED_STATE` | `requires_llm = True` or `bucket = None` |
| 4 | `SAFETY_INVALID_STRATEGY` | No strategy assigned to decision |
| 5 | `SAFETY_INVALID_AMOUNT` | `amount <= 0` |
| 6 | `SAFETY_DUPLICATE_EXECUTION` | Action already `executing` or `executed` |
| 7 | `SAFETY_INVALID_STATUS` | Decision `status != "pending"` |
| 8 | `SAFETY_STRATEGY_UNAUTHORIZED` | Strategy not valid for the decision's bucket |
| 9 | `SAFETY_MORNING_WINDOW_BLOCKED` | UPI AutoPay between 10:00–13:00 IST |
| 10 | `SAFETY_EVENING_WINDOW_BLOCKED` | UPI AutoPay between 17:00–21:30 IST |
| 11 | `SAFETY_PREDEBIT_BLIND_RETRY_FORBIDDEN` | Pre-debit notification sent < 24h before retry |
| 12 | `SAFETY_AFA_BLIND_RETRY_FORBIDDEN` | Amount > ₹15,000 without re-authentication link |
| 13 | `SAFETY_MANDATE_INACTIVE` | `mandate_status != "active"` |

---

## 7. Machine Learning Classifier

A **scikit-learn `LogisticRegression`** pipeline trained on 1,129 simulated payment-failure events.

| Metric | Value |
|---|:---:|
| Validation Accuracy | **97.5%** |
| Validation Precision | 95.2% |
| Validation Recall | 98.0% |
| Validation F1 | 96.6% |
| LLM Escalation Rate | ~8.8% of decisions |
| Confidence Threshold | **≥ 0.75** to autonomously execute |

**Features**

- **Numeric** — `amount`, `hour_of_day`, `day_of_month`, `day_of_week`, `attempt_count`, `in_congestion_window`
- **Categorical** — `decline_code`, `payment_method`, `subscription_category`

The trained model is stored at `models/recovery_classifier.joblib`. Retrain at any time:

```bash
python scripts/train_ml_model.py
```

---

## 8. LLM Reasoning Layer

When ML confidence is `< 0.75`, the event is escalated to the LLM for deep semantic reasoning. The layer is **provider-agnostic**:

| Provider | Use Case |
|---|---|
| `MockProvider` | Zero-network deterministic tests, batch simulation |
| `GeminiProvider` | Live inference via Google Gemini 2.5 Flash |
| `AnthropicProvider` | Alternative via Claude |

Set `LLM_PROVIDER` in `.env` to switch providers at runtime — no code changes required.

The LLM is constrained to return **Bucket A or B only**. Any attempt to return Bucket C is intercepted as a safety violation (`HTTP 500`).

---

## 9. Idempotency & Concurrency

The `/execute` endpoint implements a two-step idempotency protocol to prevent duplicate gateway charges under any concurrency condition:

1. **Fast lookup** — before any processing, query `RecoveryAction` by `idempotency_key`.
   - Found, status `executing` → `409 Conflict`
   - Found, status `executed`/`failed` → `200 OK` with cached result
2. **Atomic reservation** — after safety validation, insert a new `RecoveryAction` with `status="executing"` under a `UNIQUE(idempotency_key)` database constraint, committed to PostgreSQL **before** the gateway call.
3. **No lock held** — the DB transaction commits before the network call; no long-running DB lock is held across the gateway request.

**Verified result:** under 5, 10, and 20 concurrent requests with an identical `idempotency_key`, exactly **1 gateway call** is made and **0 duplicates** are recorded.

---

## 10. Project Structure

```
ai-revenue-recovery/
├── app/
│   ├── api/
│   │   ├── health.py              # GET /health, GET /system-status
│   │   ├── recovery.py            # POST /evaluate, POST /execute
│   │   └── dashboard.py           # GET /batch-summary, POST /run-batch
│   ├── core/
│   │   ├── config.py              # Pydantic settings (reads .env)
│   │   └── database.py            # SQLAlchemy session + engine
│   ├── llm/
│   │   ├── base.py                # Abstract LLMProvider interface
│   │   ├── mock_provider.py       # Deterministic mock (no network)
│   │   ├── gemini_provider.py     # Google Gemini 2.5 Flash
│   │   ├── anthropic_provider.py  # Claude provider
│   │   ├── service.py             # Provider factory + classify_with_llm()
│   │   └── models.py              # LLMResult dataclass
│   ├── models/
│   │   ├── transaction.py
│   │   ├── recovery_decision_record.py
│   │   ├── recovery_action.py
│   │   └── recovery_strategy.py
│   ├── schemas/                   # Pydantic request/response schemas
│   ├── services/
│   │   ├── regulatory_engine.py   # RBI/NPCI rules
│   │   ├── rules_classifier.py    # Decline code taxonomy
│   │   ├── ml_classifier.py       # Scikit-learn inference
│   │   ├── ml_features.py         # Feature engineering
│   │   ├── safety_validator.py    # 13-invariant checker
│   │   ├── strategy_router.py     # Adaptive strategy selection
│   │   ├── gateway_simulator.py   # Simulated payment gateway
│   │   ├── batch_simulator.py     # 150-txn demo batch
│   │   └── payment_simulator.py
│   ├── static/
│   │   ├── index.html             # Demo dashboard UI
│   │   ├── app.js                 # Frontend logic
│   │   └── style.css              # Styles
│   └── main.py                    # FastAPI app entrypoint
├── models/
│   ├── recovery_classifier.joblib          # Trained ML model
│   └── recovery_classifier_metadata.json   # Training metrics
├── alembic/                       # Database migrations
├── tests/                         # Full test suite (pytest)
├── scripts/
│   ├── train_ml_model.py          # ML model training
│   └── seed_database.py           # Database seeding
├── .env.example                   # Environment variable template
├── requirements.txt
└── alembic.ini
```

---

## 11. Setup & Running Locally

### Quick Start (Recommended for Evaluators)

The fastest path — no PostgreSQL required. Uses SQLite with `LLM_PROVIDER=mock` (no API keys needed):

```bash
# 1. Clone the repository
git clone https://github.com/harshit-karnani/ai-revenue-recovery.git
cd ai-revenue-recovery

# 2. Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create environment file
cp .env.example .env
```

Edit `.env` and set these two lines (everything else can stay as-is):

```dotenv
DATABASE_URL=sqlite:///./revguard.db
LLM_PROVIDER=mock
```

```bash
# 5. Run database migrations
alembic upgrade head

# 6. Seed demo data
python scripts/seed_database.py

# 7. Start the server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open **[http://localhost:8000/](http://localhost:8000/)** — the demo dashboard loads immediately. Click **"Run Recovery Batch"** to simulate 150 transactions.

---

### Full Setup (with PostgreSQL + Live Gemini)

For live LLM inference and production-grade database:

#### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (or a [Supabase](https://supabase.com) free-tier project)
- A [Google AI Studio](https://aistudio.google.com) API key (free tier is sufficient)

#### Clone & Install

```bash
git clone https://github.com/harshit-karnani/ai-revenue-recovery.git
cd ai-revenue-recovery

python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

#### Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
# PostgreSQL connection string
DATABASE_URL=postgresql://user:password@localhost:5432/revguard

# LLM Configuration
# Options: "mock" (no API key needed) | "gemini" | "anthropic"
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
LLM_MODEL=gemini-2.5-flash

# Optional
ML_CONFIDENCE_THRESHOLD=0.75
ENVIRONMENT=development
```

#### Run Migrations & Start

```bash
alembic upgrade head
python scripts/seed_database.py
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

| Resource | URL |
|---|---|
| Demo Dashboard | [http://localhost:8000/](http://localhost:8000/) |
| Swagger API Docs | [http://localhost:8000/docs](http://localhost:8000/docs) |
| Health Check | [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health) |
| System Status | [http://localhost:8000/api/v1/system-status](http://localhost:8000/api/v1/system-status) |

---

## 12. Running Tests

```bash
# Full test suite
pytest

# Specific test modules
pytest tests/test_part4.py -v           # Two-phase API, idempotency, concurrency
pytest tests/test_regulatory_engine.py  # RBI/NPCI rules
pytest tests/test_ml_classifier.py      # ML classifier unit tests
pytest tests/test_integration.py        # End-to-end integration

# Run only the concurrency idempotency test
pytest tests/test_part4.py -k "idempotency" -v
```

All tests run against an in-memory SQLite database via `conftest.py` — no external database required.

---

## 13. Security Scorecard

| Domain | Status | Verified Behaviour |
|---|:---:|---|
| Regulatory Firewall | ✅ PASS | Pre-debit (<24h), AFA (>₹15k/₹1L), NPCI windows enforced; 0 gateway bypasses |
| Safety Firewall | ✅ PASS | All 13 invariants independently checked before each gateway reservation |
| ML Routing | ✅ PASS | 97.5% accuracy; ambiguous codes correctly escalated below the 0.75 threshold |
| LLM Routing | ✅ PASS | Naturally engaged for low-confidence events, no force flags |
| LLM Fail-Closed | ✅ PASS | Timeout / API error → `llm_unavailable` → `403` on execute |
| LLM Bucket-C Trap | ✅ PASS | LLM Bucket C output intercepted → `500` safety violation |
| Idempotency | ✅ PASS | Duplicate executions return cached `action_id`, no re-execution |
| Concurrent Idempotency | ✅ PASS | 5 / 10 / 20 concurrent workers → exactly 1 gateway call, 0 duplicates |
| Gateway Isolation | ✅ PASS | Gateway unreachable without safety validation + atomic DB reservation |
| Timestamp Safety | ✅ PASS | UTC and IST (+05:30) parsed correctly; malformed datetimes → `422` |
| Input Validation | ✅ PASS | SQL injection, unicode fuzz, negative amounts → clean `422` |
| Database Consistency | ✅ PASS | Atomic foreign-key chains; connection pooling with pre-ping enabled |

**Test summary: 45/45 passed · 25 expected rejections confirmed · 0 unintended gateway calls.**

---

## 14. Known Limitations & Future Work

1. **Cyclic time encoding** — `hour_of_day` is currently a plain integer (0–23). Encoding it as `sin`/`cos` pairs would improve ML accuracy for patterns that cross midnight.
2. **Training data** — the ML model is trained on high-quality simulated data. The feature pipeline is production-ready and can retrain directly on real payment logs.
3. **LLM caching** — LLM responses for identical contexts are not currently cached. A Redis-backed cache would reduce latency and API costs in production.
4. **Webhook support** — the system currently operates on a request/response model. A production deployment would consume payment-gateway webhooks asynchronously.

---

<div align="center">

### Simulation Framing

The NPCI execution-window constraints (UPI AutoPay blocked 10:00–13:00 IST and 17:00–21:30 IST) are modelled as deterministic simulated failures per the 2026 BSE/NPCI circular. **No real payment gateways are called at any point in this project.**

</div>
