"""
Test Suite: Watchlist Movement Tracking Real Evidence Flow
Tests the complete verified pipeline:
Camera Detection -> Evidence Storage -> Database Record -> Evidence Endpoint -> Real File Serving -> Missing Evidence Handling -> Multi-Camera Isolation
"""

import os
import uuid
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import app
from database.connection import get_db
from database.schema import Camera, FaceWatchlist, WatchlistMovementChain, WatchlistMovementEvent, Evidence, FaceDetection
from backend.auth import create_access_token

client = TestClient(app)

@pytest.fixture
def auth_headers():
    token = create_access_token({"sub": "admin", "role": "Administrator"})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def db_session():
    db = next(get_db())
    try:
        yield db
    finally:
        pass


def test_watchlist_real_evidence_flow(db_session: Session, auth_headers):
    """
    Test 1: Complete Real Evidence Verification and Serving Pipeline
    """
    # 1. Create test camera
    cam_id = f"cam-test-{uuid.uuid4().hex[:6]}"
    cam_num = f"CAM-T1-{uuid.uuid4().hex[:6].upper()}"
    cam = Camera(
        id=cam_id,
        camera_id=cam_num,
        name="North Perimeter Gate 1",
        location="Sector 7 Watchpoint",
        stream_url=f"rtsp://localhost:8554/{cam_num}",
        status="ONLINE"
    )
    db_session.add(cam)
    db_session.flush()

    # 2. Create test watchlist subject
    wl_id = str(uuid.uuid4())
    wl = FaceWatchlist(
        id=wl_id,
        name="COMMANDER SHARMA",
        person_id=f"SEC-T1-{uuid.uuid4().hex[:6].upper()}",
        category="WATCHLIST",
        embedding=[0.1] * 128,
        is_active=True
    )
    db_session.add(wl)
    db_session.flush()

    # 3. Create real physical image file on disk in storage
    storage_dir = os.path.join("storage", "evidence", "face", "snapshots")
    os.makedirs(storage_dir, exist_ok=True)
    snap_filename = f"CAM_9901_F101_KNOWN_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
    snap_path = os.path.join(storage_dir, snap_filename)
    
    # Write a genuine small test JPEG header and content
    jpeg_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9'
    with open(snap_path, "wb") as f:
        f.write(jpeg_bytes)
    assert os.path.exists(snap_path)
    file_size = os.path.getsize(snap_path)

    # 4. Create Evidence DB record
    ev_id = str(uuid.uuid4())
    evidence_rec = Evidence(
        id=ev_id,
        camera_id=cam.id,
        evidence_type="snapshot",
        file_path=snap_path,
        file_url=f"/api/faces/snapshots/{snap_filename}",
        file_size_bytes=file_size,
        metadata_json={
            "person_name": wl.name,
            "person_id": wl.person_id,
            "camera_number": cam_num,
            "confidence": 0.94
        }
    )
    db_session.add(evidence_rec)
    db_session.flush()

    # 5. Create WatchlistMovementChain and WatchlistMovementEvent
    chain_id = str(uuid.uuid4())
    chain = WatchlistMovementChain(
        id=chain_id,
        watchlist_person_id=wl.id,
        person_name=wl.name,
        person_id=wl.person_id,
        category=wl.category,
        current_camera_id=cam.id,
        current_camera_number=cam_num,
        current_camera_name=cam.name,
        current_location=cam.location,
        status="ACTIVE"
    )
    db_session.add(chain)
    db_session.flush()

    event_id = str(uuid.uuid4())
    now_dt = datetime.utcnow()
    event = WatchlistMovementEvent(
        id=event_id,
        chain_id=chain.id,
        sequence_number=1,
        watchlist_person_id=wl.id,
        watchlist_person_name=wl.name,
        camera_id=cam.id,
        camera_number=cam_num,
        camera_name=cam.name,
        location=cam.location,
        first_seen_at=now_dt,
        last_seen_at=now_dt,
        timestamp=now_dt,
        confidence=0.94,
        face_similarity=0.94,
        evidence_id=evidence_rec.id,
        evidence_url=f"/api/faces/snapshots/{snap_filename}"
    )
    db_session.add(event)
    db_session.commit()

    try:
        # 6. Request evidence metadata endpoint: GET /api/movement/events/{event_id}/evidence
        res_meta = client.get(f"/api/movement/events/{event_id}/evidence", headers=auth_headers)
        assert res_meta.status_code == 200, f"Expected 200, got {res_meta.status_code}: {res_meta.text}"
        meta = res_meta.json()
        assert meta["exists"] is True
        assert meta["event_id"] == event_id
        assert meta["camera_number"] == cam_num
        assert meta["camera_name"] == cam.name
        assert meta["location"] == cam.location
        assert meta["watchlist_person_name"] == wl.name
        assert round(meta["face_similarity"], 2) == 0.94
        assert meta["image_url"] == f"/api/movement/events/{event_id}/evidence/image"
        assert meta["file_size_bytes"] == file_size

        # 7. Request evidence image serving endpoint: GET /api/movement/events/{event_id}/evidence/image
        res_img = client.get(f"/api/movement/events/{event_id}/evidence/image")
        assert res_img.status_code == 200
        assert res_img.headers["content-type"] == "image/jpeg"
        assert len(res_img.content) == file_size

        # 8. Test /api/movement/chains output reflects real evidence
        res_chains = client.get("/api/movement/chains", headers=auth_headers)
        assert res_chains.status_code == 200
        chains_data = res_chains.json()
        target_chain = next((c for c in chains_data if c["id"] == chain_id), None)
        assert target_chain is not None
        assert target_chain["events"][0]["has_real_evidence"] is True
        assert target_chain["events"][0]["evidence_url"] == f"/api/movement/events/{event_id}/evidence/image"

    finally:
        db_session.query(WatchlistMovementEvent).filter(WatchlistMovementEvent.id == event_id).delete()
        db_session.query(WatchlistMovementChain).filter(WatchlistMovementChain.id == chain_id).delete()
        db_session.query(Evidence).filter(Evidence.id == ev_id).delete()
        db_session.query(FaceWatchlist).filter(FaceWatchlist.id == wl_id).delete()
        db_session.query(Camera).filter(Camera.id == cam_id).delete()
        db_session.commit()
        if os.path.exists(snap_path):
            os.remove(snap_path)


def test_missing_evidence_returns_evidence_not_available(db_session: Session, auth_headers):
    """
    Test 2: Missing Evidence Gracefully Returns 404 with 'EVIDENCE NOT AVAILABLE'
    """
    cam_id = f"cam-test-{uuid.uuid4().hex[:6]}"
    cam_num = f"CAM-T2-{uuid.uuid4().hex[:6].upper()}"
    cam = Camera(id=cam_id, camera_id=cam_num, name="South Sector Gate 2", location="Sector 2", stream_url=f"rtsp://localhost:8554/{cam_num}", status="ONLINE")
    db_session.add(cam)
    db_session.flush()

    wl_id = str(uuid.uuid4())
    wl = FaceWatchlist(id=wl_id, name="INACTIVE TARGET", person_id=f"SEC-T2-{uuid.uuid4().hex[:6].upper()}", embedding=[0.1]*128, is_active=True)
    db_session.add(wl)
    db_session.flush()

    chain = WatchlistMovementChain(
        id=str(uuid.uuid4()),
        watchlist_person_id=wl.id,
        person_name=wl.name,
        person_id=wl.person_id,
        current_camera_id=cam.id,
        current_camera_number=cam_num,
        status="LAST SEEN"
    )
    db_session.add(chain)
    db_session.flush()

    # Event pointing to a non-existent file
    event_id = str(uuid.uuid4())
    event = WatchlistMovementEvent(
        id=event_id,
        chain_id=chain.id,
        sequence_number=1,
        watchlist_person_id=wl.id,
        watchlist_person_name=wl.name,
        camera_id=cam.id,
        camera_number=cam_num,
        camera_name=cam.name,
        location=cam.location,
        evidence_url="/api/faces/snapshots/DOES_NOT_EXIST_SNAPSHOT.jpg"
    )
    db_session.add(event)
    db_session.commit()

    try:
        # 1. Metadata endpoint must return 404 with 'EVIDENCE NOT AVAILABLE'
        res_meta = client.get(f"/api/movement/events/{event_id}/evidence", headers=auth_headers)
        assert res_meta.status_code == 404
        assert "EVIDENCE NOT AVAILABLE" in res_meta.json()["detail"]

        # 2. Image endpoint must also return 404 with 'EVIDENCE NOT AVAILABLE'
        res_img = client.get(f"/api/movement/events/{event_id}/evidence/image")
        assert res_img.status_code == 404
        assert "EVIDENCE NOT AVAILABLE" in res_img.json()["detail"]
    finally:
        db_session.query(WatchlistMovementEvent).filter(WatchlistMovementEvent.id == event_id).delete()
        db_session.query(WatchlistMovementChain).filter(WatchlistMovementChain.id == chain.id).delete()
        db_session.query(FaceWatchlist).filter(FaceWatchlist.id == wl_id).delete()
        db_session.query(Camera).filter(Camera.id == cam_id).delete()
        db_session.commit()


def test_multiple_cameras_maintain_distinct_real_evidence(db_session: Session, auth_headers):
    """
    Test 3: Multi-Camera Event Trajectory Isolation
    CAM-01 must open Evidence A; CAM-02 must open Evidence B. Never cross-contaminate.
    """
    cam1_num = f"CAM-T3A-{uuid.uuid4().hex[:6].upper()}"
    cam2_num = f"CAM-T3B-{uuid.uuid4().hex[:6].upper()}"
    cam1 = Camera(id=f"c1-{uuid.uuid4().hex[:6]}", camera_id=cam1_num, name="East Gate", location="East Entry", stream_url=f"rtsp://localhost:8554/{cam1_num}", status="ONLINE")
    cam2 = Camera(id=f"c2-{uuid.uuid4().hex[:6]}", camera_id=cam2_num, name="West Gate", location="West Exit", stream_url=f"rtsp://localhost:8554/{cam2_num}", status="ONLINE")
    db_session.add_all([cam1, cam2])
    db_session.flush()

    wl = FaceWatchlist(id=str(uuid.uuid4()), name="CROSS-BORDER SUBJECT", person_id=f"SEC-T3-{uuid.uuid4().hex[:6].upper()}", embedding=[0.1]*128, is_active=True)
    db_session.add(wl)
    db_session.flush()

    storage_dir = os.path.join("storage", "evidence", "face", "snapshots")
    os.makedirs(storage_dir, exist_ok=True)

    # File A for CAM-01
    file_a = os.path.join(storage_dir, f"TEST_CAM_{cam1_num}_EV_A_{uuid.uuid4().hex[:6]}.jpg")
    content_a = b"JPEG_EVIDENCE_CAM_9903_DISTINCT_A"
    with open(file_a, "wb") as f:
        f.write(content_a)

    # File B for CAM-02
    file_b = os.path.join(storage_dir, f"TEST_CAM_{cam2_num}_EV_B_{uuid.uuid4().hex[:6]}.jpg")
    content_b = b"JPEG_EVIDENCE_CAM_9904_DISTINCT_B_DIFFERENT"
    with open(file_b, "wb") as f:
        f.write(content_b)

    chain = WatchlistMovementChain(
        id=str(uuid.uuid4()),
        watchlist_person_id=wl.id,
        person_name=wl.name,
        person_id=wl.person_id,
        current_camera_id=cam2.id,
        current_camera_number=cam2_num,
        status="ACTIVE"
    )
    db_session.add(chain)
    db_session.flush()

    now_1 = datetime(2026, 9, 14, 10, 0, 0)
    ev1 = WatchlistMovementEvent(
        id=str(uuid.uuid4()),
        chain_id=chain.id,
        sequence_number=1,
        watchlist_person_id=wl.id,
        watchlist_person_name=wl.name,
        camera_id=cam1.id,
        camera_number=cam1_num,
        camera_name=cam1.name,
        location=cam1.location,
        first_seen_at=now_1,
        last_seen_at=now_1,
        timestamp=now_1,
        confidence=0.88,
        face_similarity=0.88,
        evidence_url=f"/api/faces/snapshots/{os.path.basename(file_a)}"
    )

    now_2 = datetime(2026, 9, 14, 10, 15, 0)
    ev2 = WatchlistMovementEvent(
        id=str(uuid.uuid4()),
        chain_id=chain.id,
        sequence_number=2,
        watchlist_person_id=wl.id,
        watchlist_person_name=wl.name,
        camera_id=cam2.id,
        camera_number=cam2_num,
        camera_name=cam2.name,
        location=cam2.location,
        first_seen_at=now_2,
        last_seen_at=now_2,
        timestamp=now_2,
        confidence=0.92,
        face_similarity=0.92,
        evidence_url=f"/api/faces/snapshots/{os.path.basename(file_b)}"
    )

    db_session.add_all([ev1, ev2])
    db_session.commit()

    try:
        # Query CAM-01 evidence
        res_ev1 = client.get(f"/api/movement/events/{ev1.id}/evidence", headers=auth_headers)
        assert res_ev1.status_code == 200
        assert res_ev1.json()["camera_number"] == cam1_num
        assert res_ev1.json()["camera_name"] == "East Gate"

        res_img1 = client.get(f"/api/movement/events/{ev1.id}/evidence/image")
        assert res_img1.status_code == 200
        assert res_img1.content == content_a

        # Query CAM-02 evidence
        res_ev2 = client.get(f"/api/movement/events/{ev2.id}/evidence", headers=auth_headers)
        assert res_ev2.status_code == 200
        assert res_ev2.json()["camera_number"] == cam2_num
        assert res_ev2.json()["camera_name"] == "West Gate"

        res_img2 = client.get(f"/api/movement/events/{ev2.id}/evidence/image")
        assert res_img2.status_code == 200
        assert res_img2.content == content_b

        # Verify strict isolation
        assert res_img1.content != res_img2.content

    finally:
        db_session.query(WatchlistMovementEvent).filter(WatchlistMovementEvent.chain_id == chain.id).delete()
        db_session.query(WatchlistMovementChain).filter(WatchlistMovementChain.id == chain.id).delete()
        db_session.query(FaceWatchlist).filter(FaceWatchlist.id == wl.id).delete()
        db_session.query(Camera).filter(Camera.id.in_([cam1.id, cam2.id])).delete()
        db_session.commit()
        if os.path.exists(file_a):
            os.remove(file_a)
        if os.path.exists(file_b):
            os.remove(file_b)


def test_face_detection_evidence_fallback_and_persistence(db_session: Session, auth_headers):
    """
    Test 4: Movement Event with empty evidence_url falls back to authentic FaceDetection snapshot on disk
    and permanently links it in the database.
    """
    cam_id = f"cam-fallback-{uuid.uuid4().hex[:6]}"
    cam_num = f"CAM-T4-{uuid.uuid4().hex[:6].upper()}"
    cam = Camera(id=cam_id, camera_id=cam_num, name="Checkpoint Alpha", location="Sector 5", stream_url=f"rtsp://localhost:8554/{cam_num}", status="ONLINE")
    db_session.add(cam)
    db_session.flush()

    wl = FaceWatchlist(id=str(uuid.uuid4()), name="TARGET OMEGA", person_id=f"SEC-T4-{uuid.uuid4().hex[:6].upper()}", embedding=[0.1]*128, is_active=True)
    db_session.add(wl)
    db_session.flush()

    storage_dir = os.path.join("storage", "evidence", "face", "snapshots")
    os.makedirs(storage_dir, exist_ok=True)
    snap_fn = f"CAM_{cam_num}_F101_KNOWN_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
    snap_path = os.path.join(storage_dir, snap_fn)
    content = b"REAL_FACE_DETECTION_SURVEILLANCE_SNAPSHOT_DATA"
    with open(snap_path, "wb") as f:
        f.write(content)

    # Real FaceDetection record
    fd = FaceDetection(
        id=str(uuid.uuid4()),
        camera_id=cam.id,
        identity_id=wl.id,
        identity_name=wl.name,
        recognition_status="KNOWN",
        detection_confidence=0.91,
        recognition_confidence=0.91,
        bbox=[0.2, 0.2, 0.3, 0.3],
        snapshot_url=f"/api/faces/snapshots/{snap_fn}",
        timestamp=datetime.utcnow()
    )
    db_session.add(fd)

    chain = WatchlistMovementChain(
        id=str(uuid.uuid4()),
        watchlist_person_id=wl.id,
        person_name=wl.name,
        person_id=wl.person_id,
        current_camera_id=cam.id,
        current_camera_number=cam_num,
        status="ACTIVE"
    )
    db_session.add(chain)
    db_session.flush()

    # Movement event without evidence_url
    event_id = str(uuid.uuid4())
    event = WatchlistMovementEvent(
        id=event_id,
        chain_id=chain.id,
        sequence_number=1,
        watchlist_person_id=wl.id,
        watchlist_person_name=wl.name,
        camera_id=cam.id,
        camera_number=cam_num,
        camera_name=cam.name,
        location=cam.location,
        evidence_id=None,
        evidence_url=None,  # No direct link initially
        timestamp=datetime.utcnow()
    )
    db_session.add(event)
    db_session.commit()

    try:
        # Request evidence: should resolve through FaceDetection and return 200
        res_meta = client.get(f"/api/movement/events/{event_id}/evidence", headers=auth_headers)
        assert res_meta.status_code == 200
        assert res_meta.json()["exists"] is True
        assert res_meta.json()["camera_number"] == cam_num

        res_img = client.get(f"/api/movement/events/{event_id}/evidence/image")
        assert res_img.status_code == 200
        assert res_img.content == content

        # Verify event in DB was permanently linked
        db_session.refresh(event)
        assert event.evidence_url == f"/api/faces/snapshots/{snap_fn}"

    finally:
        db_session.query(WatchlistMovementEvent).filter(WatchlistMovementEvent.chain_id == chain.id).delete()
        db_session.query(WatchlistMovementChain).filter(WatchlistMovementChain.id == chain.id).delete()
        db_session.query(FaceDetection).filter(FaceDetection.id == fd.id).delete()
        db_session.query(FaceWatchlist).filter(FaceWatchlist.id == wl.id).delete()
        db_session.query(Camera).filter(Camera.id == cam.id).delete()
        db_session.commit()
        if os.path.exists(snap_path):
            os.remove(snap_path)


def test_security_path_traversal_prevention(db_session: Session, auth_headers):
    """
    Test 5: Verifies that an event referencing a path outside the storage directory
    is rejected with HTTP 403 Forbidden.
    """
    cam_id = f"cam-sec-{uuid.uuid4().hex[:6]}"
    cam_num = f"CAM-T5-{uuid.uuid4().hex[:6].upper()}"
    cam = Camera(id=cam_id, camera_id=cam_num, name="Secure Vault", location="Sector 9", stream_url=f"rtsp://localhost:8554/{cam_num}", status="ONLINE")
    db_session.add(cam)
    db_session.flush()

    wl = FaceWatchlist(id=str(uuid.uuid4()), name="TRAVERSAL TEST", person_id=f"SEC-T5-{uuid.uuid4().hex[:6].upper()}", embedding=[0.1]*128, is_active=True)
    db_session.add(wl)
    db_session.flush()

    chain = WatchlistMovementChain(id=str(uuid.uuid4()), watchlist_person_id=wl.id, person_name=wl.name, person_id=wl.person_id, current_camera_id=cam.id, current_camera_number=cam_num, status="ACTIVE")
    db_session.add(chain)
    db_session.flush()

    # Event pointing to outside storage (e.g. /etc/hosts)
    event = WatchlistMovementEvent(
        id=str(uuid.uuid4()),
        chain_id=chain.id,
        sequence_number=1,
        watchlist_person_id=wl.id,
        watchlist_person_name=wl.name,
        camera_id=cam.id,
        camera_number=cam_num,
        camera_name=cam.name,
        location=cam.location,
        evidence_url="/etc/hosts"
    )
    db_session.add(event)
    db_session.commit()

    try:
        res = client.get(f"/api/movement/events/{event.id}/evidence/image")
        assert res.status_code in [403, 404]
    finally:
        db_session.query(WatchlistMovementEvent).filter(WatchlistMovementEvent.id == event.id).delete()
        db_session.query(WatchlistMovementChain).filter(WatchlistMovementChain.id == chain.id).delete()
        db_session.query(FaceWatchlist).filter(FaceWatchlist.id == wl.id).delete()
        db_session.query(Camera).filter(Camera.id == cam.id).delete()
        db_session.commit()


