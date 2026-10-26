import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlmodel import Session, select

from app.api import approvers, requisitions, system
from app.config import settings
from app.db.models import Requisition
from app.db.seed import seed_master_data
from app.db.session import create_tables, engine
from app.domain.workflow import State
from app.services.pipeline import process_async

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_tables()
    with Session(engine) as session:
        seed_master_data(session)
        # Anything interrupted mid-pipeline by a restart is picked up again.
        stuck = session.exec(
            select(Requisition).where(
                Requisition.state.in_([State.INBOX, State.PROCESSING, State.EXTRACTED])
            )
        ).all()  # type: ignore[attr-defined]
        for req in stuck:
            req.state = State.INBOX.value
            req.stage = None
            session.add(req)
        session.commit()
        for req in stuck:
            process_async(req.id)  # type: ignore[arg-type]
    yield


app = FastAPI(title="Purchase Requisition Automation", lifespan=lifespan)
app.include_router(requisitions.router)
app.include_router(approvers.router)
app.include_router(system.router)


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
