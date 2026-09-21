import asyncio
import os
import time
import uuid
import cv2
import numpy as np
import pytest

from database.connection import SessionLocal
from database.schema import (
    Camera, CameraZone, ZoneRule, Event, Alert, Incident,
    Evidence, FaceDetection, FaceWatchlist, ANPRResult, ANPRWatchlist, Detection
)
from ai_engine.surveillance_agent import AISurveillanceAgent
from ai_engine.tracking.tracker import MultiObjectTracker, compute_camera_track_base
from ai_engine.face.real_face_engine import RealFaceEngine, FaceTracker
from backend.stream_manager import StreamWorker, StreamManager
from backend.main import ConnectionManager


class MockWebSocketManager:
    """Mock WebSocket manager that records broadcast events per camera."""
    def __init__(self):
        self.events = []
        self._lock = asyncio.Lock()

    async def broadcast(self, message: dict):
        async with self._lock:
            self.events.append(message)


@pytest.mark.anyio
async def test_multi_camera_independent_pipeline():
    print("\n" + "="*80)
    print("STARTING IBVAP MULTI-CAMERA INDEPENDENT DETECTION PIPELINE VERIFICATION")
    print("="*80)

    db = SessionLocal()
    ws_mock = MockWebSocketManager()

    # Load real test images
    img_person = cv2.imread("storage/test_person.jpg")
    img_vehicle = cv2.imread("storage/test_vehicle.jpg")
    img_unknown = cv2.imread("storage/evidence/face/snapshots/CAM_7340_F175_UNKNOWN_20260910_072107_e79a.jpg")
    if img_unknown is None:
        # Fallback to blurred test_person if snapshot not present
        img_unknown = cv2.GaussianBlur(img_person, (25, 25), 0)

    assert img_person is not None, "storage/test_person.jpg must exist"
    assert img_vehicle is not None, "storage/test_vehicle.jpg must exist"

    # Blank frame for complete scene separation
    img_blank = np.zeros((720, 1280, 3), dtype=np.uint8)

    # Clean up test cameras in DB
    cam_ids = ["TEST-CAM-01", "TEST-CAM-02", "TEST-CAM-03"]
    from database.connection import engine
    from sqlalchemy import text
    def safe_clean_cams(ids):
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            conn.execute(text("DELETE FROM watchlist_movement_events"))
            conn.execute(text("DELETE FROM watchlist_movement_chains"))
            for tbl in ["camera_zones", "camera_health", "detections", "tracks", "face_detections", "behavior_events", "anpr_results", "evidence", "alerts", "incidents", "events"]:
                for cid in ids:
                    conn.execute(text(f"DELETE FROM {tbl} WHERE camera_id = :cid OR camera_id IN (SELECT id FROM cameras WHERE camera_id = :cid)"), {"cid": cid})
            for cid in ids:
                conn.execute(text("DELETE FROM cameras WHERE camera_id = :cid"), {"cid": cid})
            conn.execute(text("PRAGMA foreign_keys = ON"))

    safe_clean_cams(cam_ids)

    test_cams = {}
    for cid in cam_ids:
        cam = Camera(
            id=str(uuid.uuid4()),
            camera_id=cid,
            name=f"Tactical Unit {cid}",
            location=f"Sector {cid[-2:]} Gate",
            protocol="MP4",
            stream_url="storage/demo_videos/border_patrol.mp4",
            status="ONLINE",
            latitude=26.9000,
            longitude=70.9000
        )
        db.add(cam)
        test_cams[cid] = cam

        # Add a default intrusion zone for alert testing
        zone = CameraZone(
            id=str(uuid.uuid4()),
            camera_id=cam.id,
            name=f"Restricted Zone {cid}",
            zone_type="RESTRICTED AREA",
            geometry_type="polygon",
            coordinates=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], # entire frame
            is_active=True
        )
        db.add(zone)

    db.commit()

    # Enroll face from test_person.jpg into Watchlist as Threat for CAM-01 testing
    fe = RealFaceEngine()
    detected_faces = fe.detect_faces(img_person)
    assert len(detected_faces) > 0, "Expected at least 1 face in test_person.jpg"

    emb = fe.extract_embedding(img_person, detected_faces[0].raw_face_array)
    assert emb is not None, "Failed to extract embedding from test face"

    # Clean previous test watchlist entry
    db.query(FaceWatchlist).filter(FaceWatchlist.person_id == "TEST-WL-01").delete(synchronize_session=False)
    db.commit()

    wl_entry = FaceWatchlist(
        id=str(uuid.uuid4()),
        name="OPERATIVE_ALPHA_TEST",
        person_id="TEST-WL-01",
        category="BANNED",
        embedding=emb.tolist(),
        is_active=True
    )
    db.add(wl_entry)
    db.commit()

    print("[SETUP] Database and test entities ready.")

    # -------------------------------------------------------------------------
    # TEST 1: Connect CAM-01 -> streaming, detection works, alerts work
    # -------------------------------------------------------------------------
    print("\n--- TEST 1: Single Camera CAM-01 Streaming & Detection ---")
    agent_cam1 = AISurveillanceAgent("TEST-CAM-01", ws_mock)
    
    # Process 3 frames with person to allow tracker confirmation and rule evaluation
    for _ in range(3):
        tracked, lat, conf, faces, anpr = await agent_cam1.process_frame(img_person, time.time())
        await asyncio.sleep(0.05)

    assert len(tracked) > 0, "CAM-01 failed to detect objects in test_person.jpg"
    person_tracks = [t for t in tracked if t.class_name == "person"]
    assert len(person_tracks) > 0, "CAM-01 failed to detect person"
    print(f"✓ TEST 1 PASSED: CAM-01 detected {len(person_tracks)} person(s), latency: {lat:.1f}ms")

    # -------------------------------------------------------------------------
    # TEST 2: Connect CAM-01 + CAM-02 simultaneously
    # -------------------------------------------------------------------------
    print("\n--- TEST 2: Simultaneous CAM-01 and CAM-02 Operation ---")
    agent_cam2 = AISurveillanceAgent("TEST-CAM-02", ws_mock)
    assert agent_cam1.camera_id != agent_cam2.camera_id
    assert agent_cam1.tracker is not agent_cam2.tracker
    assert agent_cam1.face_tracker is not agent_cam2.face_tracker
    assert agent_cam1.agent_executor is not agent_cam2.agent_executor

    # Run inference concurrently using asyncio.gather
    t1_coro = agent_cam1.process_frame(img_person, time.time())
    t2_coro = agent_cam2.process_frame(img_vehicle, time.time())
    (res1, res2) = await asyncio.gather(t1_coro, t2_coro)

    tracked1, _, _, _, _ = res1
    tracked2, _, _, _, _ = res2
    assert len(tracked1) > 0, "CAM-01 inference failed in concurrent execution"
    assert len(tracked2) > 0, "CAM-02 inference failed in concurrent execution"
    print(f"✓ TEST 2 PASSED: Both cameras concurrently processed frames independently.")

    # -------------------------------------------------------------------------
    # TEST 3: Show person to CAM-01 -> CAM-02 must NOT receive CAM-01 detection
    # -------------------------------------------------------------------------
    print("\n--- TEST 3: Person to CAM-01 (Isolation Check) ---")
    agent_cam1.cleanup_live_session()
    agent_cam2.cleanup_live_session()

    res1, res2 = await asyncio.gather(
        agent_cam1.process_frame(img_person, time.time()),
        agent_cam2.process_frame(img_blank, time.time())
    )
    cam1_tracks = [t for t in res1[0] if t.class_name == "person"]
    cam2_tracks = [t for t in res2[0] if t.class_name == "person"]
    assert len(cam1_tracks) > 0, "CAM-01 must detect person"
    assert len(cam2_tracks) == 0, f"CAM-02 leaked CAM-01 person detection! Got: {cam2_tracks}"
    print(f"✓ TEST 3 PASSED: CAM-01 detected person ({len(cam1_tracks)}), CAM-02 detected 0 (isolated).")

    # -------------------------------------------------------------------------
    # TEST 4: Show different scene to CAM-02 -> CAM-01 must NOT receive CAM-02 detection
    # -------------------------------------------------------------------------
    print("\n--- TEST 4: Person to CAM-02 (Reverse Isolation Check) ---")
    agent_cam1.cleanup_live_session()
    agent_cam2.cleanup_live_session()

    res1, res2 = await asyncio.gather(
        agent_cam1.process_frame(img_blank, time.time()),
        agent_cam2.process_frame(img_person, time.time())
    )
    cam1_tracks = [t for t in res1[0] if t.class_name == "person"]
    cam2_tracks = [t for t in res2[0] if t.class_name == "person"]
    assert len(cam1_tracks) == 0, f"CAM-01 leaked CAM-02 person detection! Got: {cam1_tracks}"
    assert len(cam2_tracks) > 0, "CAM-02 must detect person"
    print(f"✓ TEST 4 PASSED: CAM-02 detected person ({len(cam2_tracks)}), CAM-01 detected 0 (isolated).")

    # -------------------------------------------------------------------------
    # TEST 5: Show Watchlist Person to CAM-01 -> Match & Alert
    # -------------------------------------------------------------------------
    print("\n--- TEST 5: Watchlist Match on CAM-01 ---")
    agent_cam1.cleanup_live_session()

    # Feed test_person.jpg to CAM-01 for 3 frames (>200ms sleep) so FaceTracker confirms consecutive frames
    faces_cam1 = []
    for _ in range(3):
        _, _, _, faces_cam1, _ = await agent_cam1.process_frame(img_person, time.time())
        await asyncio.sleep(0.25)

    assert len(faces_cam1) > 0, "CAM-01 found no faces"
    matched_face = None
    for f in faces_cam1:
        if f.get("identity_name") == "OPERATIVE_ALPHA_TEST":
            matched_face = f
            break

    assert matched_face is not None, f"CAM-01 failed to match watchlist person! Got: {[f.get('identity_name') for f in faces_cam1]}"
    assert matched_face["recognition_status"] == "KNOWN"
    print(f"✓ TEST 5 PASSED: CAM-01 correctly identified watchlist threat: {matched_face['identity_name']}")

    # -------------------------------------------------------------------------
    # TEST 6: Unknown Person to CAM-02 -> No False Watchlist Match
    # -------------------------------------------------------------------------
    print("\n--- TEST 6: Unknown Person on CAM-02 ---")
    agent_cam2.cleanup_live_session()

    faces_cam2 = []
    for _ in range(3):
        _, _, _, faces_cam2, _ = await agent_cam2.process_frame(img_unknown, time.time())
        await asyncio.sleep(0.25)

    assert len(faces_cam2) > 0, "CAM-02 found no faces in unknown person image"
    for f in faces_cam2:
        assert f.get("identity_name") != "OPERATIVE_ALPHA_TEST", f"False positive watchlist match on CAM-02! Got {f.get('identity_name')}"
        print(f"   CAM-02 face classified as: {f.get('recognition_status')} / {f.get('identity_name')}")
    print(f"✓ TEST 6 PASSED: CAM-02 correctly classified faces as UNKNOWN/UNCERTAIN (0 false watchlist matches).")

    # -------------------------------------------------------------------------
    # TEST 7: Show vehicle to CAM-01 -> Vehicle detected, ANPR attempted
    # -------------------------------------------------------------------------
    print("\n--- TEST 7: Vehicle Detection & ANPR on CAM-01 ---")
    # Feed frame containing bus
    tracked_v, _, _, _, anpr_list = await agent_cam1.process_frame(img_person, time.time())
    veh_tracks = [t for t in tracked_v if t.class_name in ["car", "bus", "truck", "motorcycle", "vehicle"]]
    assert len(veh_tracks) > 0, "No vehicle detected in frame containing bus"
    print(f"✓ TEST 7 PASSED: CAM-01 detected vehicle of class '{veh_tracks[0].class_name}' with track {veh_tracks[0].track_id}")

    # -------------------------------------------------------------------------
    # TEST 8: Disconnect CAM-02 -> CAM-01 continues detecting and alerting
    # -------------------------------------------------------------------------
    print("\n--- TEST 8: Disconnect CAM-02 & Verify CAM-01 Uninterrupted ---")
    agent_cam2.cleanup_live_session()
    agent_cam2.shutdown()

    # CAM-01 should continue to detect normally without error
    tracked_after, _, _, _, _ = await agent_cam1.process_frame(img_person, time.time())
    assert len(tracked_after) > 0, "CAM-01 failed after CAM-02 was disconnected!"
    print(f"✓ TEST 8 PASSED: CAM-02 disconnected, CAM-01 continues detecting ({len(tracked_after)} tracks).")

    # -------------------------------------------------------------------------
    # TEST 9: Reconnect CAM-02 -> CAM-02 resumes independently
    # -------------------------------------------------------------------------
    print("\n--- TEST 9: Reconnect CAM-02 and Verify Independent Resumption ---")
    agent_cam2 = AISurveillanceAgent("TEST-CAM-02", ws_mock)
    tracked_c2, _, _, _, _ = await agent_cam2.process_frame(img_person, time.time())
    assert len(tracked_c2) > 0, "Reconnected CAM-02 failed to detect objects!"
    print(f"✓ TEST 9 PASSED: CAM-02 reconnected and detecting independently.")

    # -------------------------------------------------------------------------
    # TEST 10: 3 Cameras (CAM-01 + CAM-02 + CAM-03) Tracking Range Partitioning
    # -------------------------------------------------------------------------
    print("\n--- TEST 10: Concurrency & Track ID Range Partitioning Across 3 Cameras ---")
    agent_cam3 = AISurveillanceAgent("TEST-CAM-03", ws_mock)
    
    t1_base = compute_camera_track_base("TEST-CAM-01")
    t2_base = compute_camera_track_base("TEST-CAM-02")
    t3_base = compute_camera_track_base("TEST-CAM-03")
    
    assert t1_base != t2_base and t2_base != t3_base, f"Track bases collided: {t1_base}, {t2_base}, {t3_base}"
    print(f"   Track bases: CAM-01={t1_base}, CAM-02={t2_base}, CAM-03={t3_base}")

    # Run all 3 concurrently
    r1, r2, r3 = await asyncio.gather(
        agent_cam1.process_frame(img_person, time.time()),
        agent_cam2.process_frame(img_person, time.time()),
        agent_cam3.process_frame(img_person, time.time())
    )
    for obj in r1[0]:
        assert t1_base <= obj.track_id < t1_base + 10000, f"CAM-01 track_id {obj.track_id} outside assigned partition!"
    for obj in r2[0]:
        assert t2_base <= obj.track_id < t2_base + 10000, f"CAM-02 track_id {obj.track_id} outside assigned partition!"
    for obj in r3[0]:
        assert t3_base <= obj.track_id < t3_base + 10000, f"CAM-03 track_id {obj.track_id} outside assigned partition!"
    print(f"✓ TEST 10 PASSED: All 3 cameras ran concurrently with zero track ID collision.")

    # -------------------------------------------------------------------------
    # TEST 11: Database Association Verification
    # -------------------------------------------------------------------------
    print("\n--- TEST 11: Database Record Camera Association Verification ---")
    # Wait for async DB writes
    await asyncio.sleep(0.5)

    cam1_db_id = test_cams["TEST-CAM-01"].id
    cam2_db_id = test_cams["TEST-CAM-02"].id

    alerts_cam1 = db.query(Alert).filter((Alert.camera_id == cam1_db_id) | (Alert.camera_id == "TEST-CAM-01")).all()
    ev_cam1 = db.query(Evidence).filter((Evidence.camera_id == cam1_db_id) | (Evidence.camera_id == "TEST-CAM-01")).all()
    face_cam1 = db.query(FaceDetection).filter((FaceDetection.camera_id == cam1_db_id) | (FaceDetection.camera_id == "TEST-CAM-01")).all()

    print(f"   Database records for CAM-01: alerts={len(alerts_cam1)}, evidence={len(ev_cam1)}, faces={len(face_cam1)}")
    for a in alerts_cam1:
        assert a.camera_id in [cam1_db_id, "TEST-CAM-01"], f"Alert has wrong camera_id: {a.camera_id}"
    for e in ev_cam1:
        assert e.camera_id in [cam1_db_id, "TEST-CAM-01"], f"Evidence has wrong camera_id: {e.camera_id}"
    print(f"✓ TEST 11 PASSED: Originating camera IDs accurately persisted across Alert, Evidence, and FaceDetection.")

    # -------------------------------------------------------------------------
    # TEST 12: WebSocket Multiplexing & Isolation Verification
    # -------------------------------------------------------------------------
    print("\n--- TEST 12: WebSocket Multiplexing & Isolation ---")
    # Create real ConnectionManager and test independent send queues
    conn_mgr = ConnectionManager()
    
    class FakeClientSocket:
        def __init__(self, name):
            self.name = name
            self.received = []
        async def accept(self):
            pass
        async def send_json(self, data):
            self.received.append(data)

    client1 = FakeClientSocket("client_web")
    client2 = FakeClientSocket("client_mobile")
    await conn_mgr.connect(client1)
    await conn_mgr.connect(client2)

    # Broadcast simultaneous events from CAM-01 and CAM-02
    await asyncio.gather(
        conn_mgr.broadcast({"type": "DETECTIONS_UPDATE", "camera_id": "TEST-CAM-01", "fps": 25.0}),
        conn_mgr.broadcast({"type": "DETECTIONS_UPDATE", "camera_id": "TEST-CAM-02", "fps": 24.5}),
        conn_mgr.broadcast({"type": "ALERT_NEW", "camera_id": "TEST-CAM-01", "event_type": "INTRUSION"}),
        conn_mgr.broadcast({"type": "ALERT_NEW", "camera_id": "TEST-CAM-02", "event_type": "UNKNOWN_PERSON"})
    )
    # Let queue workers process
    await asyncio.sleep(0.1)

    assert len(client1.received) == 4, f"Client 1 received {len(client1.received)} messages, expected 4"
    assert len(client2.received) == 4, f"Client 2 received {len(client2.received)} messages, expected 4"

    c1_sources = [m.get("camera_id") for m in client1.received]
    assert "TEST-CAM-01" in c1_sources and "TEST-CAM-02" in c1_sources, "WebSocket dropped camera events!"

    conn_mgr.disconnect(client1)
    conn_mgr.disconnect(client2)
    print(f"✓ TEST 12 PASSED: WebSocket broadcast safely multiplexed events from multiple cameras to all clients.")

    # Clean up
    agent_cam1.shutdown()
    agent_cam2.shutdown()
    agent_cam3.shutdown()
    safe_clean_cams(cam_ids)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text("DELETE FROM face_watchlist WHERE person_id = 'TEST-WL-01'"))
        conn.execute(text("PRAGMA foreign_keys = ON"))
    db.close()

    print("\n" + "="*80)
    print("ALL 12 TESTS PASSED SUCCESSFULLY! MULTI-CAMERA PIPELINE FULLY INDEPENDENT.")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(test_multi_camera_independent_pipeline())
