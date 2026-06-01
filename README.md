# FinSafe Idempotency Gateway

### Architecture 

<img width="938" height="2009" alt="image" src="https://github.com/user-attachments/assets/b23deac3-79d7-4b03-9437-143ac2fefe24" />

A backend middleware service built to solve a real problem — when e-commerce clients retry failed payment requests, customers get charged twice. This gateway ensures every payment is processed **exactly once**, no matter how many times the request is sent.

---

## 🚀 Live API

[Test the Live API](https://idempotency-gateway-production-87f3.up.railway.app)

*Note: The API may take a few seconds to respond on the first request as the server spins up from idle.*

```
Quick test endpoint:
GET https://idempotency-gateway-production-87f3.up.railway.app/
```

---

## 🔧 How It Works

When a client sends a payment request, the gateway checks Redis for the `Idempotency-Key` header:

- **New key** → process the payment, save the result, return `201`
- **Seen key, same payload** → return the saved result instantly, no charge
- **Seen key, different payload** → return `409 Conflict`
- **No key provided** → auto-generate one from the payload hash
- **In-flight duplicate** → wait for the first request to finish, return its result

---

## 💻 Setup Guide

### Prerequisites

- Python 3.11+
- Redis ([Memurai](https://www.memurai.com/) for Windows)
- Git

### Option 1 — Use the Live API

No setup needed. Just open Postman and send requests to:
```
https://idempotency-gateway-production-87f3.up.railway.app/process-payment
```

### Option 2 — Run Locally

**1. Clone the repository**

```bash
git clone https://github.com/ephraimb04/idempotency-gateway.git
cd idempotency-gateway
```

**2. Create and activate a virtual environment**

```bash
# Create
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Set up environment variables**

Create a `.env` file in the root directory:

```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
```

*Note: Copy `.env.example` as a template*

**5. Make sure Redis is running**

Start Memurai (Windows) or run `redis-server` (Mac/Linux) on port `6379`.

**6. Start the server**

```bash
uvicorn main:app --reload
```

Server runs at `http://127.0.0.1:8000`

---

## 📡 API Documentation

### Base URLs

```
Local:   http://127.0.0.1:8000
Live:    https://idempotency-gateway-production-87f3.up.railway.app
```

---

### `GET /`

Health check.

**Response:**
```json
{
    "status": "FinSafe Idempotency Gateway is running"
}
```

---

### `POST /process-payment`

Handles payment requests with idempotency protection.

**Headers:**

| Header | Required | Description |

| `Idempotency-Key` | No | Unique ID per payment attempt. Auto-generated if not sent. |
| `Content-Type` | Yes | `application/json` |

**Request Body:**

| Field | Type | Description |

| `amount` | float | Payment amount |
| `currency` | string | Currency code e.g. `GHS`, `USD` |

**Example:**
```json
{
    "amount": 50,
    "currency": "GHS"
}
```

---

### Response Scenarios

**New payment — `201 Created`**
```json
{
    "message": "Charged 50.0 GHS",
    "idempotency_key": "pay_test_001",
    "status": "success",
    "amount": 50.0,
    "currency": "GHS"
}
```

**Duplicate blocked — `200 OK`**

Headers include `X-Cache-Hit: true` and `X-Retry-Count: 1`

```json
{
    "message": "Charged 50.0 GHS",
    "idempotency_key": "pay_test_001",
    "status": "success",
    "amount": 50.0,
    "currency": "GHS"
}
```

**Conflict — `409 Conflict`**
```json
{
    "detail": "Idempotency key already used for a different request body."
}
```

**No key sent — auto-generated key**
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

## 🧠 Design Decisions

**Why FastAPI?**
I needed async support to handle concurrent duplicate requests without blocking. FastAPI handles this cleanly and Pydantic validates the request body automatically which saved me writing extra validation code.

**Why Redis?**
The whole solution depends on checking a key atomically — if two requests arrive at the same time, only one should get through. Redis `SET NX` does this in a single operation with no gap where a race condition can sneak in. The built-in key expiry (`EX 86400`) also means I don't need to write any cleanup logic — keys just disappear after 24 hours.

**Why a proxy middleware?**
I didn't want to touch FinSafe's existing payment service at all. Sitting in front of it as a proxy means the original code is never at risk, and the same middleware could protect other endpoints in the future without any changes.

**Why Railway over AWS?**
Honestly, practicality. Railway doesn't require a credit card, has a built-in Redis service, and auto-deploys on every push. The app is also pre-configured with Mangum so when an AWS account is available, migration is straightforward.

---

## ✨ Developer's Choice — Retry Counter

I added an `X-Retry-Count` header that tracks how many times a duplicate request has been blocked for a given key.

```
First request:   201 Created  —  X-Cache-Hit: false
Second request:  200 OK       —  X-Cache-Hit: true, X-Retry-Count: 1
Third request:   200 OK       —  X-Cache-Hit: true, X-Retry-Count: 2
```

I added this because in a real fintech environment, retry counts are useful data. A customer retrying twice is normal — a client retrying 40 times means something is broken on their end. This header gives engineers visibility into that without any extra database queries since Redis `INCR` is instant.

---

## 🛠 Tech Stack

- **Language:** Python 3.14
- **Framework:** FastAPI
- **Key Store:** Redis
- **Server:** Uvicorn
- **Cloud:** Railway
- **AWS Adapter:** Mangum (for future Lambda migration)

---

## 📁 File Structure

```
idempotency-gateway/
├── main.py              # All application logic
├── requirements.txt     # Dependencies
├── Procfile             # Railway start command
├── nixpacks.toml        # Railway build config
├── lambda_handler.py    # AWS Lambda entry point
├── template.yaml        # AWS SAM config
├── flowchart.png        # Architecture diagram
├── .env.example         # Environment variable template
├── .gitignore
└── README.md
```

---

## 📝 Notes

- `.env` is excluded from the repository for security — use `.env.example` as a template
- Keys expire automatically after 24 hours
- Work was done in the railway variant and files were committed to the main 
- For any issues feel free to open an [issue on GitHub](https://github.com/ephraimb04/idempotency-gateway/issues)
