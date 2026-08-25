import asyncio
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import audit  # noqa: E402
from .db import Base, engine  # noqa: E402
from .routers.actions_api import router as actions_router  # noqa: E402
from .routers.api import router as api_router  # noqa: E402

app = FastAPI(title="RevPulse API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(engine)
app.include_router(api_router)
app.include_router(actions_router)


@app.on_event("startup")
async def _startup():
    audit.register_loop(asyncio.get_running_loop())


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
