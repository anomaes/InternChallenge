"""Client for the customer's ERP (mock_po_api.py)."""

import time
from dataclasses import dataclass

import httpx

from app.config import settings


@dataclass
class ERPResponse:
    status: int | None  # None = never reached the ERP
    body: dict
    error: str | None = None


def post_purchase_order(payload: dict, idempotency_key: str, attempts: int = 3) -> ERPResponse:
    """POST with an Idempotency-Key, retrying connection errors with backoff. A retry after
    a lost response returns the order already booked instead of booking it twice."""
    delay = 0.5
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            res = httpx.post(
                f"{settings.erp_base_url}/purchase-orders",
                json=payload,
                headers={"Idempotency-Key": idempotency_key},
                timeout=10.0,
            )
            try:
                body = res.json()
            except ValueError:
                body = {"error": res.text[:500]}
            return ERPResponse(res.status_code, body if isinstance(body, dict) else {"data": body})
        except httpx.HTTPError as err:
            last_error = f"{type(err).__name__}: {err}"
            if attempt < attempts:
                time.sleep(delay)
                delay *= 2
    return ERPResponse(None, {}, error=f"ERP unreachable after {attempts} attempts ({last_error})")


def erp_health() -> str:
    try:
        res = httpx.get(f"{settings.erp_base_url}/health", timeout=1.0)
        return "ok" if res.status_code == 200 else f"http {res.status_code}"
    except httpx.HTTPError:
        return "unreachable"
