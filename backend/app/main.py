from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import Base, engine

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


@app.get("/health")
def health():
    return {"status": "ok"}
