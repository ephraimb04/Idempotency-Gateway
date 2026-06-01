import asyncio
import hashlib
import json
import os
from datetime import datetime

import redis
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import BaseModel

# Load environment variables from .env 
load_dotenv()

#  FastAPI app 
app = FastAPI(title="FinSafe Idempotency Gateway")

#  Redis connection (supports Railway's password)
r = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD", None),
    decode_responses=True,
)

#  Request body model


class PaymentRequest(BaseModel):
    amount: float
    currency: str


#  Helper: hash the request body so we can detect conflicts 
def hash_payload(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


# Helper: auto-generate a key if the client forgot to send one 
def generate_fingerprint(payload: dict) -> str:
    window = datetime.utcnow().strftime("%Y-%m-%dT%H:%M")  # 1-minute window
    raw = json.dumps(payload, sort_keys=True) + window
    return "auto_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


# Root endpoint (health check) 
@app.get("/")
def root():
    return {"status": "FinSafe Idempotency Gateway is running"}


# Main payment endpoint 
@app.post("/process-payment")
async def process_payment(
    payment: PaymentRequest,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
):
    payload_dict = payment.model_dump()
    payload_hash = hash_payload(payload_dict)

    # If no key supplied, auto-generate one from the payload 
    if not idempotency_key:
        idempotency_key = generate_fingerprint(payload_dict)

    # Redis key names
    status_key = f"{idempotency_key}:status"
    response_key = f"{idempotency_key}:response"
    hash_key = f"{idempotency_key}:hash"
    retry_key = f"{idempotency_key}:retries"

    # Check if this key already exists 
    existing_status = r.get(status_key)

    # STORY 3: Same key, different payload 
    if existing_status:
        stored_hash = r.get(hash_key)
        if stored_hash and stored_hash != payload_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key already used for a different request body.",
            )

    # BONUS: In-flight check — wait for Request A to finish 
    if existing_status == "processing":
        # Poll every 200ms until done (max 10 seconds)
        for _ in range(50):
            await asyncio.sleep(0.2)
            current = r.get(status_key)
            if current == "done":
                break
        # Fall through to return the stored response below

    # STORY 2: Duplicate request — return stored response 
    if r.get(status_key) == "done":
        stored_response = r.get(response_key)
        retry_count = r.incr(retry_key)  # Developer's Choice: count retries
        response_data = json.loads(stored_response)
        return JSONResponse(
            content=response_data,
            headers={
                "X-Cache-Hit": "true",
                "X-Retry-Count": str(retry_count),
            },
        )

    # STORY 1: Brand new request — process the payment 

    # Mark as in-flight so concurrent duplicates wait
    r.set(status_key,   "processing", ex=86400)
    r.set(hash_key,     payload_hash, ex=86400)
    r.set(retry_key,    "0",          ex=86400)

    # Simulate payment processing (2-second delay)
    await asyncio.sleep(2)

    # Build the success response
    response_data = {
        "message":         f"Charged {payment.amount} {payment.currency}",
        "idempotency_key": idempotency_key,
        "status":          "success",
        "amount":          payment.amount,
        "currency":        payment.currency,
    }

    # Save result and mark as done
    r.set(response_key, json.dumps(response_data), ex=86400)
    r.set(status_key,   "done",                    ex=86400)

    return JSONResponse(
        content=response_data,
        status_code=201,
        headers={"X-Cache-Hit": "false"},
    )


# AWS Lambda handler (for future AWS deployment) 
handler = Mangum(app)


# Run the server locally 
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
