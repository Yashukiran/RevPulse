import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'revpulse.db'}")

# Resolve relative sqlite paths against backend/ so scripts work from any cwd
if DATABASE_URL.startswith("sqlite:///./"):
    DATABASE_URL = f"sqlite:///{BACKEND_DIR / DATABASE_URL.removeprefix('sqlite:///./')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utc_iso(dt) -> str | None:
    """Serialise a stored timestamp as explicit UTC.

    Everything is stored as naive UTC; without the trailing marker a browser
    reads the string as local time and renders "5h ago" for something that just
    happened.
    """
    if dt is None:
        return None
    return dt.isoformat() + ("Z" if dt.tzinfo is None else "")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_columns() -> None:
    """Add columns introduced after a database was first created.

    The review extraction cached in this database was paid for, so the schema is
    widened in place rather than recreated. SQLite only supports ADD COLUMN,
    which is all these changes need.
    """
    from sqlalchemy import text

    wanted = {
        "opportunities": [("recoverable_revenue_inr", "INTEGER DEFAULT 0")],
        "campaigns": [("control_ids_json", "TEXT")],
    }
    with engine.begin() as conn:
        for table, columns in wanted.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:
                continue  # table not created yet; metadata.create_all will handle it
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
