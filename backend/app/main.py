import asyncio
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import audit  # noqa: E402
from .db import Base, engine, ensure_columns  # noqa: E402
from .routers.actions_api import router as actions_router  # noqa: E402
from .routers.api import router as api_router  # noqa: E402
from .routers.demand_api import router as demand_router  # noqa: E402
from .routers.opportunities_api import router as opportunities_router  # noqa: E402

app = FastAPI(title="RevPulse API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_origin_regex=r"https://.*\.(vercel\.app|onrender\.com)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(engine)
ensure_columns()
app.include_router(api_router)
app.include_router(actions_router)
app.include_router(opportunities_router)
app.include_router(demand_router)


@app.on_event("startup")
async def _startup():
    audit.register_loop(asyncio.get_running_loop())
    # The agent works without being asked: if nothing is currently on the
    # merchant's desk, look for opportunities as soon as we come up.
    asyncio.get_running_loop().run_in_executor(None, _startup_scan)


def _startup_scan() -> None:
    from . import opportunities
    from .db import SessionLocal
    from .models import Opportunity

    db = SessionLocal()
    try:
        pending = db.query(Opportunity).filter(
            Opportunity.status.in_(["open", "awaiting_approval"])).count()
        if pending == 0:
            opportunities.scan(db)
    except Exception:
        pass  # a failed scan must never stop the API from serving
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/audit")
async def audit_ws(ws: WebSocket):
    await ws.accept()
    audit.subscribe(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive; client sends pings
    except WebSocketDisconnect:
        pass
    finally:
        audit.unsubscribe(ws)


@app.websocket("/ws/reviews")
async def reviews_ws(ws: WebSocket):
    await ws.accept()
    audit.subscribe_reviews(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        audit.unsubscribe_reviews(ws)
