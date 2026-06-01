# FinSafe Idempotency Gateway

A middleware service that ensures payment requests are processed **exactly once**, preventing double charges caused by network timeouts and client retries.

## 1. Architecture Diagram

![Idempotency Gateway Flowchart](flowchart.png)

### How the Flow Works

### Step How it works 

 1.  Client sends `POST /process-payment` with an `Idempotency-Key` header 
 2  Gateway receives the request 
 3  If no key provided → auto-generate one from payload hash 
 4  Check Redis — does this key already exist? 
 5  If key exists + same payload → return stored response (no charge) 
 5  If key exists + different payload → return `409 Conflict` 
 5  If key is new → forward to payment service 
 6  Save result to Redis with 24hr expiry 
 7  Return payment response to client 

## 2. Setup Instructions

### Prerequisites

- Python 3.11 or higher
- Redis (Memurai for Windows / Redis for Mac or Linux)
- Git

### Option 1 — Use the Live API (No Setup Needed)

The API is already deployed and running at:

https://your-app.up.railway.app/process-payment

Just open Postman and send requests directly. No installation required.

### Option 2 — Run Locally

**Step 1 — Clone the repository**
```bash
git clone https://github.com/ephraimb04/idempotency-gateway.git
cd idempotency-gateway
```

**Step 2 — Create and activate virtual environment**

Windows:
```bash
python -m venv venv
venv\Scripts\activate
```

Mac/Linux:
```bash
python -m venv venv
source venv/bin/activate
```

**Step 3 — Install dependencies**
```bash
pip install -r requirements.txt
```

**Step 4 — Set up environment variables**
```bash
cp .env.example .env
```

Open `.env` and fill in your local Redis details:
```
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
```

**Step 5 — Start Redis**

Make sure Redis or Memurai is running on port `6379`.

**Step 6 — Run the server**
```bash
uvicorn main:app --reload
```

Server runs at: `http://127.0.0.1:8000`


## 3. API Documentation

### Base URL

```
Local:  http://127.0.0.1:8000
Live:   https://YOUR-RAILWAY-URL.up.railway.app
```

### Endpoints

---

#### GET /

Health check to confirm the service is running.

**Request:**

GET /

**Response:**
```json
{
    "status": "FinSafe Idempotency Gateway is running"
}
```

---

#### POST /process-payment

Process a payment with full idempotency protection.

**Headers:**

| Header | Required | Description |

| `Idempotency-Key` | No | Unique key per payment attempt. Auto-generated if missing. |
| `Content-Type` | Yes | `application/json` |

**Request Body:**

| Field | Type | Required | Description |

| `amount` | float | Yes | Payment amount |
| `currency` | string | Yes | Currency code e.g. GHS, USD |

**Example Request:**
```json
{
    "amount": 50,
    "currency": "GHS"
}
```

---

### Response Scenarios

#### Story 1 — New Payment (Happy Path)
```
Status:       201 Created
X-Cache-Hit:  false
```
```json
{
    "message": "Charged 50.0 GHS",
    "idempotency_key": "pay_test_001",
    "status": "success",
    "amount": 50.0,
    "currency": "GHS"
}
```

---

#### Story 2 — Duplicate Request Blocked
```
Status:         200 OK
X-Cache-Hit:    true
X-Retry-Count:  1
```
```json
{
    "message": "Charged 50.0 GHS",
    "idempotency_key": "pay_test_001",
    "status": "success",
    "amount": 50.0,
    "currency": "GHS"
}
```

---

#### Story 3 — Conflict (Same Key, Different Amount)
```
Status: 409 Conflict
```
```json
{
    "detail": "Idempotency key already used for a different request body."
}
```

---

#### Bonus — No Key Provided (Auto-Generated)
```
Status:       Payment service response created 
X-Cache-Hit:  false
```
```json
{
    "message": "Charged 50.0 GHS",
    "idempotency_key": "auto_7de163e407f6cae8",
    "status": "success",
    "amount": 50.0,
    "currency": "GHS"
}
```

---

### Testing With Postman

**Test 1 — Happy Path:**
1. Set method to `POST`
2. URL: `https://YOUR-RAILWAY-URL.up.railway.app/process-payment`
3. Headers: `Idempotency-Key: pay_test_001`
4. Body (raw JSON): `{ "amount": 50, "currency": "GHS" }`
5. Click Send → expect `Payment service created`

**Test 2 — Duplicate:**
1. Send the exact same request again
2. Expect `200 OK` with `X-Cache-Hit: true`

**Test 3 — Conflict:**
1. Keep same `Idempotency-Key: pay_test_001`
2. Change amount to `99`
3. Expect `409 Conflict`

---

## 4. Design Decisions

### Why FastAPI?

FastAPI was chosen because:
- **Async support** — handles concurrent duplicate requests without blocking threads
- **Pydantic validation** — automatically validates and rejects malformed request bodies
- **Auto docs** — visit `/docs` for a live interactive API explorer
- **Performance** — one of the fastest Python web frameworks available

### Why Redis?

Redis was chosen as the idempotency key store because:
- **Atomic `SET NX`** — checks and claims a key in one indivisible operation, eliminating race conditions completely
- **Sub-millisecond speed** — duplicate detection adds virtually zero latency to the payment flow
- **Built-in key expiry** — keys automatically delete after 24 hours (`EX 86400`) with no cleanup code needed
- **In-memory storage** — data lives in RAM, not on disk, making every lookup instant

### Why a Proxy Middleware Approach?

Rather than modifying FinSafe's existing payment service:
- **Non-invasive** — existing payment logic is never touched, reducing risk
- **Reusable** — protects any endpoint, not just payments
- **Independently deployable** — can be scaled, updated, and monitored separately

### Race Condition Handling

When two identical requests arrive at the exact same time:
1. Request A claims the key with `SET NX` → status set to `processing`
2. Request B finds status = `processing` → enters a polling loop
3. Request B checks every 200ms for up to 10 seconds
4. When Request A completes → Request B returns the same result
5. Payment service is called exactly once — no double charge

### Why Railway Over AWS?

Railway was chosen for deployment because:
- **No credit card required** — accessible for developers in any region including Ghana
- **Managed Redis** — built-in Redis with zero configuration
- **Auto-deploy** — GitHub pushes automatically trigger redeployments
- **AWS-ready** — Mangum is included so migration to Lambda requires only 5 commands

---

## 5. Developer's Choice Feature

### Feature: Retry Counter (`X-Retry-Count` Header)

**What it does:**

Every time a duplicate request is detected and blocked, a counter increments in Redis and is returned in the response header as `X-Retry-Count`.

**Example:**
```
First request:   201 Created  →  X-Cache-Hit: false
Second request:  200 OK       →  X-Cache-Hit: true,  X-Retry-Count: 1
Third request:   200 OK       →  X-Cache-Hit: true,  X-Retry-Count: 2
Fourth request:  200 OK       →  X-Cache-Hit: true,  X-Retry-Count: 3
```

**Why I added it:**

In a real-world Fintech company like FinSafe, knowing how many times a client retries the same payment is critical operational data. This feature helps engineers:

- **Identify unstable connections** — a high retry count signals network problems on the client side
- **Detect client bugs** — if a client retries 50 times, something is wrong with their implementation
- **Regulatory compliance** — provides an audit trail proving the system prevented duplicate charges
- **Proactive alerting** — the retry count can trigger monitoring alerts if retries become excessive

This feature adds full observability to the idempotency layer with zero performance cost since Redis `INCR` is an O(1) operation — instant regardless of counter size.

---

## Tech Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.14 | Core language |
| FastAPI | Latest | Web framework |
| Redis | Latest | Idempotency key store |
| Uvicorn | Latest | ASGI server |
| Mangum | Latest | AWS Lambda adapter |
| python-dotenv | Latest | Environment variable management |
| Railway | - | Cloud deployment platform |

---

## File Structure

```
idempotency-gateway/
├── main.py              # Core application logic
├── requirements.txt     # Python dependencies
├── Procfile             # Railway start command
├── nixpacks.toml        # Railway build configuration
├── lambda_handler.py    # AWS Lambda entry point
├── template.yaml        # AWS SAM deployment config
├── flowchart.png        # Architecture diagram
├── .env.example         # Environment variable template
├── .gitignore           # Files excluded from Git
└── README.md            # This file
```

---

## Author

**Ephraim** — Built as part of the AmalitechGlobal Backend Engineering Challenge
 
 
