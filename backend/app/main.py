import httpx
from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="Purchase Requisition Automation")


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Liveness of this API plus reachability of the mock ERP."""
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            res = await client.get(f"{settings.erp_base_url}/health")
        erp = "ok" if res.status_code == 200 else f"http {res.status_code}"
    except httpx.HTTPError:
        erp = "unreachable"
    return {"status": "ok", "erp": erp}
