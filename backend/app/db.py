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

IS_SQLITE = DATABASE_URL.startswith("sqlite")

# SQLite is the default so the project can be cloned and run with no database to
# provision — that reproducibility is the whole reason for the choice, not a
# belief that it scales. Nothing here is SQLite-specific: every column type in
# models.py is portable and the app issues no raw SQL, so pointing DATABASE_URL
# at Postgres is the only change required.
#
#   DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/revpulse
#
# The two settings below are the only engine-dependent lines in the codebase.
if IS_SQLITE:
    # SQLite refuses cross-thread use by default; a web server needs it lifted.
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # A networked database wants pooling and dead-connection detection instead.
    engine = create_engine(
        DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True,
    )
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
    """Add columns introduced after this database was first created.

    The review extraction cached in the committed SQLite file was paid for once,
    so the schema is widened in place rather than recreated. SQLite only supports
    ADD COLUMN, which is all these changes need.

    Deliberately a no-op on any other engine. This is a fifteen-line stand-in for
    a migration tool, justified only by not wanting to re-pay for extraction on a
    single-file demo database. A Postgres deployment should run Alembic instead —
    reading the live schema and generating reversible migrations — rather than
    trust a hand-maintained list of columns.
    """
    if not IS_SQLITE:
        return

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


# Run at import: scripts and the API both open the database this way, and a
# schema older than the code would fail at the first write rather than here.
try:
    ensure_columns()
except Exception:
    pass  # a database that does not exist yet is created by metadata.create_all
