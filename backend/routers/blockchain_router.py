"""
IBVAP Blockchain Audit Trail REST Router
==========================================

Exposes the blockchain-style tamper-evident audit chain via REST API.

Endpoints:
  GET /api/blockchain/chain        - Full audit chain (paginated)
  GET /api/blockchain/verify       - Verify chain integrity
  GET /api/blockchain/block/{event_id} - Get block for a specific event
  GET /api/blockchain/stats        - Chain statistics
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import AuditBlock
from backend.auth import get_current_user
from backend.blockchain_audit import verify_chain, get_block_for_event

router = APIRouter(prefix="/api/blockchain", tags=["Blockchain Audit Trail"])


@router.get("/verify")
def verify_audit_chain(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Verify the cryptographic integrity of the entire audit chain.

    Returns:
        valid (bool): True if all blocks are tamper-free.
        total_blocks: Total number of blocks in chain.
        verified_blocks: Number of blocks that passed verification.
        first_broken_at: Block index of the first tampered block (null if valid).
        message: Human-readable integrity status.
    """
    result = verify_chain(db)
    return result


@router.get("/chain")
def get_audit_chain(
    limit: int = 100,
    offset: int = 0,
    event_type: Optional[str] = None,
    camera_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Return the audit chain blocks in descending order (newest first).
    Supports pagination via limit/offset and filtering by event_type or camera_id.
    """
    query = db.query(AuditBlock)
    if event_type:
        query = query.filter(AuditBlock.event_type == event_type)
    if camera_id:
        query = query.filter(AuditBlock.camera_id == camera_id)

    total = query.count()
    blocks = (
        query
        .order_by(AuditBlock.block_index.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "blocks": [
            {
                "id": b.id,
                "block_index": b.block_index,
                "event_type": b.event_type,
                "event_id": b.event_id,
                "camera_id": b.camera_id,
                "event_data_hash": b.event_data_hash,
                "previous_hash": b.previous_hash,
                "block_hash": b.block_hash,
                "timestamp": f"{b.timestamp.isoformat()}Z" if b.timestamp else None,
                "created_at": f"{b.created_at.isoformat()}Z" if b.created_at else None,
            }
            for b in blocks
        ]
    }


@router.get("/block/{event_id}")
def get_block_by_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get the audit block that protects a specific alert, incident, or evidence record.

    Args:
        event_id: The alert_id, incident_id, or evidence_id to look up.

    Returns:
        The matching audit block, or 404 if not found.
    """
    block = get_block_for_event(db, event_id)
    if not block:
        raise HTTPException(
            status_code=404,
            detail=f"No audit block found for event_id={event_id}. "
                   "The event may predate blockchain implementation."
        )
    return {
        "id": block.id,
        "block_index": block.block_index,
        "event_type": block.event_type,
        "event_id": block.event_id,
        "camera_id": block.camera_id,
        "event_data_hash": block.event_data_hash,
        "previous_hash": block.previous_hash,
        "block_hash": block.block_hash,
        "timestamp": f"{block.timestamp.isoformat()}Z" if block.timestamp else None,
        "created_at": f"{block.created_at.isoformat()}Z" if block.created_at else None,
    }


@router.get("/stats")
def get_chain_stats(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Chain statistics: total blocks by event type, genesis block info, latest block.
    """
    from sqlalchemy import func
    total_blocks = db.query(AuditBlock).count()

    # Count by event type
    type_counts = (
        db.query(AuditBlock.event_type, func.count(AuditBlock.id))
        .group_by(AuditBlock.event_type)
        .all()
    )

    genesis = db.query(AuditBlock).order_by(AuditBlock.block_index.asc()).first()
    latest = db.query(AuditBlock).order_by(AuditBlock.block_index.desc()).first()

    return {
        "total_blocks": total_blocks,
        "blocks_by_type": {str(t): int(c) for t, c in type_counts},
        "genesis_block": {
            "block_index": genesis.block_index,
            "block_hash": genesis.block_hash,
            "timestamp": f"{genesis.timestamp.isoformat()}Z" if genesis and genesis.timestamp else None,
        } if genesis else None,
        "latest_block": {
            "block_index": latest.block_index,
            "block_hash": latest.block_hash,
            "timestamp": f"{latest.timestamp.isoformat()}Z" if latest and latest.timestamp else None,
        } if latest else None,
        "chain_description": (
            "SHA-256 hash chain. Each block: block_hash = SHA256(event_data_hash + previous_hash). "
            "Provides tamper-evident integrity for all security alerts and incidents."
        )
    }
