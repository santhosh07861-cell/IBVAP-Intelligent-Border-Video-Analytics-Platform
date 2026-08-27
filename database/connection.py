import os
import logging
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

# Load environment variables from .env manually without external dependency
if os.path.exists(".env"):
    try:
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
    except Exception:
        pass

logger = logging.getLogger(__name__)

DEFAULT_PG_URL = "postgresql://postgres:postgres@localhost:5432/ibvap"
DEFAULT_SQLITE_URL = "sqlite:///./ibvap.db"

# Prefer explicit env variable, default to SQLite if not specified or PG not configured
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)

def _make_sqlite_engine(url: str):
    eng = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 15},
        poolclass=NullPool,
        echo=False
    )
    @event.listens_for(eng, "connect")
    def set_sqlite_pragmas(dbapi_conn, connection_record):
        try:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
        except Exception:
            pass
    return eng

def _make_pg_engine(url: str):
    return create_engine(
        url,
        connect_args={"connect_timeout": 2},
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False
    )

engine = None

if DATABASE_URL.startswith("sqlite"):
    engine = _make_sqlite_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("DATABASE ENGINE: SQLite")
    logger.info("DATABASE STATUS: CONNECTED")
    print("DATABASE ENGINE: SQLite")
    print("DATABASE STATUS: CONNECTED")
else:
    # Try PostgreSQL, fallback to SQLite if connection fails
    try:
        engine = _make_pg_engine(DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("DATABASE ENGINE: PostgreSQL")
        logger.info("DATABASE STATUS: CONNECTED")
        print("DATABASE ENGINE: PostgreSQL")
        print("DATABASE STATUS: CONNECTED")
    except Exception as err:
        logger.warning(f"PostgreSQL failed ({err}). Falling back to SQLite ({DEFAULT_SQLITE_URL}).")
        print(f"DATABASE WARNING: PostgreSQL failed. Falling back to SQLite ({DEFAULT_SQLITE_URL}).")
        DATABASE_URL = DEFAULT_SQLITE_URL
        engine = _make_sqlite_engine(DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("DATABASE ENGINE: SQLite (Fallback)")
        logger.info("DATABASE STATUS: CONNECTED")
        print("DATABASE ENGINE: SQLite (Fallback)")
        print("DATABASE STATUS: CONNECTED")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
