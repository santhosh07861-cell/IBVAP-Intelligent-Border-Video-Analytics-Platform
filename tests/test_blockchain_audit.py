import pytest
from database.connection import SessionLocal, Base, engine
from database.schema import AuditBlock
from backend.blockchain_audit import (
    create_audit_block,
    verify_chain,
    get_block_for_event,
    compute_event_hash,
    compute_block_hash,
    GENESIS_HASH
)

@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_hash_computation():
    event_data = {"alert_id": "AL-001", "risk_score": 85.0}
    event_hash = compute_event_hash(event_data)
    assert isinstance(event_hash, str)
    assert len(event_hash) == 64

    block_hash = compute_block_hash(event_hash, GENESIS_HASH)
    assert isinstance(block_hash, str)
    assert len(block_hash) == 64

def test_chain_verification_intact(db_session):
    result = verify_chain(db_session)
    assert result["valid"] is True
