import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# Primary Live Operational Database URL (Default: PostgreSQL)
DEFAULT_PG_URL = "postgresql://postgres:postgres@localhost:5432/ibvap"
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
    
    logger.info("DATABASE ENGINE: PostgreSQL")
    logger.info("DATABASE HOST: localhost")
    logger.info("DATABASE NAME: ibvap")
    logger.info("DATABASE STATUS: CONNECTED")
    print("DATABASE ENGINE: PostgreSQL")
    print("DATABASE HOST: localhost")
    print("DATABASE NAME: ibvap")
    print("DATABASE STATUS: CONNECTED")

except Exception as err:
    # Try alternative local user socket before declaring failure
    try:
        engine = create_engine(
            alt_url,
            connect_args=connect_args,
            poolclass=NullPool,
            echo=False
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("DATABASE ENGINE: PostgreSQL")
        logger.info("DATABASE HOST: localhost")
        logger.info("DATABASE NAME: ibvap")
        logger.info("DATABASE STATUS: CONNECTED")
        print("DATABASE ENGINE: PostgreSQL")
        print("DATABASE HOST: localhost")
        print("DATABASE NAME: ibvap")
        print("DATABASE STATUS: CONNECTED")
        DATABASE_URL = alt_url
    except Exception as err2:
        logger.error(f"DATABASE STATUS: DISCONNECTED - PostgreSQL connection failed: {err2}")
        print("DATABASE ENGINE: PostgreSQL")
        print("DATABASE HOST: localhost")
        print("DATABASE NAME: ibvap")
        print(f"DATABASE STATUS: DISCONNECTED ({err2})")
        raise RuntimeError(f"DATABASE: DISCONNECTED - PostgreSQL connection failed ({err2}). Live SQLite fallback is disabled.")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
