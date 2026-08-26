import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# Primary Live Operational Database URL (Default: PostgreSQL)
DEFAULT_PG_URL = "postgresql://postgres:postgres@localhost:5432/ibvap"
DEFAULT_SQLITE_URL = "sqlite:///./ibvap.db"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_PG_URL)

# Fallback to local OS user if default postgres role requires alternate socket
if "postgres:postgres" in DATABASE_URL:
    alt_url = f"postgresql://{os.getenv('USER', 'postgres')}@localhost:5432/ibvap"
else:
    alt_url = DEFAULT_PG_URL

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30}

try:
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        poolclass=NullPool,
        echo=False
    )
    # Validate connection immediately
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    
    db_engine_name = "SQLite" if DATABASE_URL.startswith("sqlite") else "PostgreSQL"
    logger.info(f"DATABASE ENGINE: {db_engine_name}")
    logger.info("DATABASE STATUS: CONNECTED")
    print(f"DATABASE ENGINE: {db_engine_name}")
    print("DATABASE STATUS: CONNECTED")

except Exception as err:
    if not DATABASE_URL.startswith("sqlite"):
        # Try alternative local user socket before falling back to SQLite
        try:
            engine = create_engine(
                alt_url,
                connect_args={},
                poolclass=NullPool,
                echo=False
            )
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("DATABASE ENGINE: PostgreSQL")
            logger.info("DATABASE STATUS: CONNECTED")
            print("DATABASE ENGINE: PostgreSQL")
            print("DATABASE STATUS: CONNECTED")
            DATABASE_URL = alt_url
        except Exception as err2:
            logger.warning(f"PostgreSQL connection failed ({err2}). Falling back to SQLite.")
            print(f"DATABASE WARNING: PostgreSQL failed ({err2}). Falling back to SQLite database ({DEFAULT_SQLITE_URL}).")
            DATABASE_URL = DEFAULT_SQLITE_URL
            engine = create_engine(
                DATABASE_URL,
                connect_args={"check_same_thread": False, "timeout": 30},
                poolclass=NullPool,
                echo=False
            )
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("DATABASE ENGINE: SQLite (Fallback)")
            logger.info("DATABASE STATUS: CONNECTED")
            print("DATABASE ENGINE: SQLite (Fallback)")
            print("DATABASE STATUS: CONNECTED")
    else:
        logger.error(f"SQLite connection failed: {err}")
        raise err

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
