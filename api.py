from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

EMAIL = "23f2004539@ds.study.iitm.ac.in"
EXAM_ORIGIN = "https://exam.sanand.workers.dev"
ALLOWED_ORIGIN = "https://app-1i6w1w.example.com"
app = FastAPI()

# Sliding-window buckets are isolated by endpoint and caller supplied client ID.
_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_orders: dict[str, dict[str, str]] = {}


@app.middleware("http")
async def request_context_and_rate_limit(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id

    policy = None
    if request.url.path == "/ping":
        policy = ("ping", 13)
    elif request.url.path in {"/orders", "/orders/"}:
        policy = ("orders", 20)

    if policy and request.method != "OPTIONS":
        bucket_name, maximum = policy
        client_id = request.headers.get("x-client-id", "default")
        bucket = _buckets[(bucket_name, client_id)]
        now = time.monotonic()
        while bucket and now - bucket[0] >= 10:
            bucket.popleft()
        if len(bucket) >= maximum:
            from starlette.responses import JSONResponse

            response = JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": "10"},
            )
        else:
            bucket.append(now)
            response = await call_next(request)
    else:
        response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=[EXAM_ORIGIN, ALLOWED_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


@app.get("/ping")
async def ping(request: Request):
    return {"email": EMAIL, "request_id": request.state.request_id}


@app.post("/orders", status_code=201)
async def create_order(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key required")
    if idempotency_key not in _orders:
        _orders[idempotency_key] = {"id": str(uuid.uuid4()), "status": "created"}
    return _orders[idempotency_key]


@app.get("/orders")
async def list_orders(
    limit: int = Query(default=10, ge=1, le=100), cursor: str | None = None
):
    try:
        offset = int(cursor) if cursor else 0
    except ValueError:
        offset = 0
    offset = max(0, min(offset, 43))
    items = [{"id": n} for n in range(offset + 1, min(43, offset + limit) + 1)]
    next_offset = offset + len(items)
    return {
        "items": items,
        "next_cursor": str(next_offset) if next_offset < 43 else None,
    }
