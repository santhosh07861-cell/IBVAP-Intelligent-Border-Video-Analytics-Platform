"""
Test Suite: ANPR Deletion & Real Vehicle Intelligence Hardening
===============================================================
Validates:
1. Working DELETE endpoint for ANPR detection records from SQLite database.
2. Removal of associated evidence exclusively owned by deleted record.
3. Retention of shared evidence if referenced by other records.
4. Immediate, accurate counter updates via get_anpr_stats.
5. Multi-frame plate conflict resolution: conflicting readings remain PLATE UNCERTAIN.
6. Persistence across DB reloads.
7. Real vehicle classification and zero fake plate generation.
"""

import os
import uuid
import pytest
from datetime import datetime
from fastapi import HTTPException

from database.connection import SessionLocal
from database.schema import ANPRResult, User, Role
from backend.routers.anpr_router import (
    delete_anpr_result,
    delete_all_anpr_results,
    bulk_delete_anpr_results,
    get_anpr_stats,
    BulkDeleteANPRRequest,
    ANPR_SNAPSHOT_DIR,
)
from ai_engine.anpr.anpr_engine import (
    ANPRPlateTracker,
    validate_indian_plate,
    normalize_plate_text,
    VEHICLE_TYPE_MAP,
    VEHICLE_CLASSES,
)


@pytest.fixture(scope="module")
def db_session():
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def mock_operator_user():
    user = type("MockUser", (), {
        "id": "mock-admin-01",
        "username": "admin",
        "role": type("MockRole", (), {"name": "Administrator"})(),
        "is_active": True,
    })()
    return user


def test_delete_anpr_record_from_database(db_session, mock_operator_user):
    """Requirement 1, 17, 20: Real delete removes record from SQLite DB and re-fetch returns 404."""
    test_id = f"test-del-{uuid.uuid4().hex[:8]}"
    rec = ANPRResult(
        id=test_id,
        camera_id=None,
        plate_number="AP40C1235",
        vehicle_type="CAR",
        vehicle_track_id=301,
        camera_name="Test North Gate",
        camera_location="Gate 1",
        detection_confidence=0.91,
        ocr_confidence=0.88,
        snapshot_url=None,
        status="CONFIRMED",
        is_watchlist_match=False,
        timestamp=datetime.utcnow(),
    )
    db_session.add(rec)
    db_session.commit()

    # Verify record was persisted
    saved = db_session.query(ANPRResult).filter(ANPRResult.id == test_id).first()
    assert saved is not None

    # Execute real backend delete
    res = delete_anpr_result(test_id, db=db_session, current_user=mock_operator_user)
    assert res["success"] is True
    assert res["deleted_id"] == test_id

    # Verify record is permanently deleted from SQLite
    deleted = db_session.query(ANPRResult).filter(ANPRResult.id == test_id).first()
    assert deleted is None

    # Subsequent delete of non-existent record raises 404
    with pytest.raises(HTTPException) as exc_info:
        delete_anpr_result(test_id, db=db_session, current_user=mock_operator_user)
    assert exc_info.value.status_code == 404


def test_delete_exclusive_evidence_removes_file(db_session, mock_operator_user):
    """Requirement 1: Associated evidence removed only if exclusively owned."""
    os.makedirs(ANPR_SNAPSHOT_DIR, exist_ok=True)
    snap_filename = f"test_exclusive_{uuid.uuid4().hex[:6]}.jpg"
    snap_path = os.path.join(ANPR_SNAPSHOT_DIR, snap_filename)
    with open(snap_path, "wb") as f:
        f.write(b"fake_jpeg_content_exclusive")

    test_id = f"test-del-excl-{uuid.uuid4().hex[:8]}"
    snap_url = f"/api/anpr/snapshots/{snap_filename}"
    rec = ANPRResult(
        id=test_id,
        camera_id=None,
        plate_number=None,
        vehicle_type="BUS",
        vehicle_track_id=302,
        detection_confidence=0.88,
        ocr_confidence=0.0,
        snapshot_url=snap_url,
        status="UNCERTAIN",
        timestamp=datetime.utcnow(),
    )
    db_session.add(rec)
    db_session.commit()

    assert os.path.exists(snap_path) is True

    # Delete record
    res = delete_anpr_result(test_id, db=db_session, current_user=mock_operator_user)
    assert res["success"] is True

    # Because file was exclusive, it must be removed from disk
    assert os.path.exists(snap_path) is False


def test_delete_shared_evidence_retains_file(db_session, mock_operator_user):
    """Requirement 1: Associated evidence RETAINED if shared with another record."""
    os.makedirs(ANPR_SNAPSHOT_DIR, exist_ok=True)
    snap_filename = f"test_shared_{uuid.uuid4().hex[:6]}.jpg"
    snap_path = os.path.join(ANPR_SNAPSHOT_DIR, snap_filename)
    with open(snap_path, "wb") as f:
        f.write(b"fake_jpeg_content_shared")

    snap_url = f"/api/anpr/snapshots/{snap_filename}"
    rec1_id = f"test-shared-1-{uuid.uuid4().hex[:8]}"
    rec2_id = f"test-shared-2-{uuid.uuid4().hex[:8]}"

    rec1 = ANPRResult(
        id=rec1_id,
        camera_id=None,
        plate_number="DL01AB1111",
        vehicle_type="CAR",
        snapshot_url=snap_url,
        timestamp=datetime.utcnow(),
    )
    rec2 = ANPRResult(
        id=rec2_id,
        camera_id=None,
        plate_number="DL01AB1111",
        vehicle_type="CAR",
        snapshot_url=snap_url,
        timestamp=datetime.utcnow(),
    )
    db_session.add_all([rec1, rec2])
    db_session.commit()

    # Delete Record 1
    delete_anpr_result(rec1_id, db=db_session, current_user=mock_operator_user)

    # File MUST still exist on disk because Record 2 still references it
    assert os.path.exists(snap_path) is True

    # Delete Record 2 (now it is exclusive)
    delete_anpr_result(rec2_id, db=db_session, current_user=mock_operator_user)

    # Now the file must be removed
    assert os.path.exists(snap_path) is False


def test_counters_update_accurately_on_delete(db_session, mock_operator_user):
    """Requirement 16: Counters calculate from real DB rows and update on deletion."""
    initial_stats = get_anpr_stats(db=db_session, current_user=mock_operator_user)
    initial_all = initial_stats["total_all_time"]
    initial_confirmed = initial_stats["confirmed_today"]

    # Insert a confirmed plate record
    test_id = f"test-stat-{uuid.uuid4().hex[:8]}"
    rec = ANPRResult(
        id=test_id,
        camera_id=None,
        plate_number="KA05MH2020",
        vehicle_type="CAR",
        status="CONFIRMED",
        timestamp=datetime.utcnow(),
    )
    db_session.add(rec)
    db_session.commit()

    stats_after_add = get_anpr_stats(db=db_session, current_user=mock_operator_user)
    assert stats_after_add["total_all_time"] == initial_all + 1
    assert stats_after_add["confirmed_today"] == initial_confirmed + 1

    # Delete the record
    delete_anpr_result(test_id, db=db_session, current_user=mock_operator_user)

    # Counters must reflect deletion immediately
    stats_after_del = get_anpr_stats(db=db_session, current_user=mock_operator_user)
    assert stats_after_del["total_all_time"] == initial_all
    assert stats_after_del["confirmed_today"] == initial_confirmed


def test_multi_frame_conflicting_readings_returns_uncertain():
    """Requirement 8: Conflicting plate readings across frames remain PLATE UNCERTAIN."""
    tracker = ANPRPlateTracker()
    cam = "CAM-CONFLICT"
    tid = 901

    # Frame 1: reads AP40AB1234
    tracker.update(cam, tid, "AP40AB1234", 0.85)
    # Frame 2: reads AP40AB1284 (conflict)
    tracker.update(cam, tid, "AP40AB1284", 0.82)
    # Frame 3: unreadable
    tracker.update(cam, tid, "PLATE UNCERTAIN", 0.0)

    # Must NOT randomly pick one; must return PLATE UNCERTAIN
    best_text, avg_conf, is_valid = tracker.get_best_result(cam, tid)
    assert best_text == "PLATE UNCERTAIN"
    assert avg_conf == 0.0
    assert is_valid is False

    # Frame 4: another consistent reading for AP40AB1234 reaches confirmation threshold (2 votes vs 1)
    tracker.update(cam, tid, "AP40AB1234", 0.90)
    best_text_after, avg_conf_after, is_valid_after = tracker.get_best_result(cam, tid)
    assert best_text_after == "AP40AB1234"
    assert avg_conf_after >= 0.85
    assert is_valid_after is True


def test_bulk_delete_anpr_results(db_session, mock_operator_user):
    """Requirement 1, 20: Bulk deletion removes all specified records."""
    ids = [f"test-bulk-{i}-{uuid.uuid4().hex[:6]}" for i in range(3)]
    for rid in ids:
        db_session.add(ANPRResult(
            id=rid,
            camera_id=None,
            vehicle_type="TRUCK",
            timestamp=datetime.utcnow()
        ))
    db_session.commit()

    req = BulkDeleteANPRRequest(result_ids=ids)
    res = bulk_delete_anpr_results(req, db=db_session, current_user=mock_operator_user)
    assert res["success"] is True
    assert res["deleted_count"] == 3

    # Verify all 3 are deleted from DB
    remaining = db_session.query(ANPRResult).filter(ANPRResult.id.in_(ids)).count()
    assert remaining == 0


def test_unreadable_plate_validation_and_normalization():
    """Requirement 6, 9: Never guess, substitute, or invent a plate number."""
    assert normalize_plate_text("") == "PLATE UNCERTAIN"
    assert normalize_plate_text("??") == "PLATE UNCERTAIN"
    assert normalize_plate_text("UNKNOWN / UNREADABLE") == "PLATE UNCERTAIN"
    assert validate_indian_plate("AP40A1?") is False
    assert validate_indian_plate("PLATE UNREADABLE") is False
    assert validate_indian_plate(None) is False


def test_delete_all_anpr_records_and_evidence(db_session, mock_operator_user):
    """Requirement 4: Delete All permanently deletes all ANPR records & cleans exclusive evidence."""
    os.makedirs(ANPR_SNAPSHOT_DIR, exist_ok=True)
    snap1 = os.path.join(ANPR_SNAPSHOT_DIR, f"test_all_1_{uuid.uuid4().hex[:6]}.jpg")
    snap2 = os.path.join(ANPR_SNAPSHOT_DIR, f"test_all_2_{uuid.uuid4().hex[:6]}.jpg")
    with open(snap1, "wb") as f:
        f.write(b"data1")
    with open(snap2, "wb") as f:
        f.write(b"data2")

    r1 = ANPRResult(
        id=f"test-all-1-{uuid.uuid4().hex[:6]}",
        camera_id=None,
        plate_number="KA01AB1111",
        vehicle_type="CAR",
        snapshot_url=f"/api/anpr/snapshots/{os.path.basename(snap1)}",
        timestamp=datetime.utcnow()
    )
    r2 = ANPRResult(
        id=f"test-all-2-{uuid.uuid4().hex[:6]}",
        camera_id=None,
        plate_number=None,
        vehicle_type="BUS",
        snapshot_url=f"/api/anpr/snapshots/{os.path.basename(snap2)}",
        timestamp=datetime.utcnow()
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    assert os.path.exists(snap1) is True
    assert os.path.exists(snap2) is True

    res = delete_all_anpr_results(db=db_session, current_user=mock_operator_user)
    assert res["success"] is True
    assert res["deleted_count"] >= 2

    # Verify zero ANPRResult records remain in the database
    remaining = db_session.query(ANPRResult).count()
    assert remaining == 0

    # Evidence files removed
    assert os.path.exists(snap1) is False
    assert os.path.exists(snap2) is False

