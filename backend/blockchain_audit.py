"""
IBVAP Blockchain-Style Tamper-Evident Audit Trail
===================================================

Every security alert and incident creates an immutable 'block' in a cryptographic
hash chain. Any tampering with historical event data will break the chain and be
detected immediately by verify_chain().

Hash Chain Design:
  genesis block:   previous_hash = '0' * 64
  block N:
      event_data_hash = SHA-256(canonical_json(event_data))
      block_hash      = SHA-256(event_data_hash + previous_hash)

NOTE: This is a software-defined tamper-evident log - NOT a distributed blockchain
network. It provides cryptographic audit integrity within the IBVAP system.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session
from database.schema import AuditBlock

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


def _canonical_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_event_hash(event_data: Dict[str, Any]) -> str:
    canonical = _canonical_json(event_data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_block_hash(event_data_hash: str, previous_hash: str) -> str:
    chain_input = (event_data_hash + previous_hash).encode("utf-8")
    return hashlib.sha256(chain_input).hexdigest()


def _get_last_block(db: Session) -> Optional[AuditBlock]:
    return db.query(AuditBlock).order_by(AuditBlock.block_index.desc()).first()


def create_audit_block(
    db: Session,
    event_type: str,
    event_id: str,
    event_data: Dict[str, Any],
    camera_id: Optional[str] = None,
) -> AuditBlock:
    """
    Create and persist a new audit block in the chain.
    Caller must commit the session after calling this function.

    Args:
        db:          Active SQLAlchemy session.
        event_type:  e.g. "ALERT_CREATED", "INCIDENT_CREATED", "EVIDENCE_CREATED"
        event_id:    ID of the alert/incident/evidence record being protected.
        event_data:  The event payload to fingerprint (must be JSON-serializable).
        camera_id:   Optional camera that generated the event.

    Returns:
        The AuditBlock instance (added to session, not yet committed).
    """
    last_block = _get_last_block(db)
    previous_hash = last_block.block_hash if last_block else GENESIS_HASH
    block_index = (last_block.block_index + 1) if last_block else 0

    event_data_hash = compute_event_hash(event_data)
    block_hash = compute_block_hash(event_data_hash, previous_hash)

    now = datetime.utcnow()
    block = AuditBlock(
        id=str(uuid.uuid4()),
        block_index=block_index,
        event_type=event_type,
        event_id=event_id,
        camera_id=camera_id,
        event_data_hash=event_data_hash,
        previous_hash=previous_hash,
        block_hash=block_hash,
        timestamp=now,
        created_at=now,
    )
    db.add(block)

    logger.info(
        f"[AUDIT_BLOCK_CREATED] block_index={block_index} event_type={event_type} "
        f"event_id={event_id} block_hash={block_hash[:16]}..."
    )
    return block


def verify_chain(db: Session) -> Dict[str, Any]:
    """
    Verify the integrity of the entire audit chain.
    Returns a dict with valid, total_blocks, verified_blocks, first_broken_at, message.
    """
    blocks = db.query(AuditBlock).order_by(AuditBlock.block_index.asc()).all()

    if not blocks:
        return {
            "valid": True,
            "total_blocks": 0,
            "verified_blocks": 0,
            "first_broken_at": None,
            "broken_block_id": None,
            "message": "Chain is empty - no audit blocks yet."
        }

    expected_previous = GENESIS_HASH
    broken_at = None
    broken_id = None

    for block in blocks:
        if block.previous_hash != expected_previous:
            broken_at = block.block_index
            broken_id = block.id
            logger.error(f"[CHAIN_BREAK] block_index={block.block_index} id={block.id}")
            break

        expected_hash = compute_block_hash(block.event_data_hash, block.previous_hash)
        if expected_hash != block.block_hash:
            broken_at = block.block_index
            broken_id = block.id
            logger.error(f"[BLOCK_TAMPERED] block_index={block.block_index} id={block.id}")
            break

        expected_previous = block.block_hash

    total = len(blocks)
    is_valid = broken_at is None
    verified = broken_at if broken_at is not None else total

    result = {
        "valid": is_valid,
        "total_blocks": total,
        "verified_blocks": verified,
        "first_broken_at": broken_at,
        "broken_block_id": broken_id,
        "message": (
            f"Chain integrity verified. All {total} blocks are tamper-free."
            if is_valid
            else f"Chain BROKEN at block index {broken_at}. Blocks 0-{broken_at - 1} intact."
        )
    }
    logger.info(f"[CHAIN_VERIFY] valid={is_valid} total={total} verified={verified} broken_at={broken_at}")
    return result


def get_block_for_event(db: Session, event_id: str) -> Optional[AuditBlock]:
    """Retrieve the audit block protecting a specific event."""
    return db.query(AuditBlock).filter(AuditBlock.event_id == event_id).first()
