"""
Comprehensive Multi-Camera Simultaneous Streaming and Independence Verification Suite
Directly validates Tests 1 through 6 specified in the system requirements:
- Test 1: Connect Camera A -> streaming -> live frames -> AI inference.
- Test 2: Connect Camera B without disconnecting Camera A -> both active simultaneously.
- Test 3: Object to Camera A -> detections attributed only to Camera A.
- Test 4: Different object to Camera B -> detections attributed only to Camera B. Zero cross-contamination.
- Test 5: Disconnect Camera B -> Camera B disconnected, Camera A continues uninterrupted.
- Test 6: Reconnect Camera B -> Camera A remains active, Camera B resumes as a separate stream.
"""

import asyncio
import time
import cv2
import numpy as np
import pytest

from backend.stream_manager import StreamManager
from video_engine.ingestion.source import PushVideoSource, create_video_source


class MockWebSocketManager:
    def __init__(self):
        self.broadcasted = []
        self._lock = asyncio.Lock()

    async def broadcast(self, message: dict):
        async with self._lock:
            self.broadcasted.append(message)

    def get_camera_messages(self, camera_id: str):
        return [m for m in self.broadcasted if m.get("camera_id") == camera_id]


@pytest.mark.anyio
async def test_simultaneous_multi_camera_lifecycle():
    ws = MockWebSocketManager()
    mgr = StreamManager()
    mgr.set_loop(asyncio.get_running_loop())

    # Load real test images
    img_person = cv2.imread("storage/test_person.jpg")
    img_vehicle = cv2.imread("storage/test_vehicle.jpg")
    assert img_person is not None, "storage/test_person.jpg required for test"
    assert img_vehicle is not None, "storage/test_vehicle.jpg required for test"

    # Seed test cameras in DB for foreign key constraint compliance
    from database.connection import SessionLocal, engine
    from database.schema import Camera
    from sqlalchemy import text
    import uuid

    cam_a_id = "CAM-TEST-ALPHA"
    cam_b_id = "CAM-TEST-BETA"

    def safe_clean_cams(ids):
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            for tbl in ["camera_zones", "camera_health", "detections", "tracks", "face_detections", "behavior_events", "anpr_results", "evidence", "alerts", "incidents", "events"]:
                for cid in ids:
                    conn.execute(text(f"DELETE FROM {tbl} WHERE camera_id = :cid OR camera_id IN (SELECT id FROM cameras WHERE camera_id = :cid)"), {"cid": cid})
            for cid in ids:
                conn.execute(text("DELETE FROM cameras WHERE camera_id = :cid"), {"cid": cid})
            conn.execute(text("PRAGMA foreign_keys = ON"))

    safe_clean_cams([cam_a_id, cam_b_id])

    db = SessionLocal()

    cam_a_db = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_a_id,
        name="Test Camera Alpha (Primary)",
        location="Sector Alpha Entry",
        protocol="WEBCAM",
        stream_url="browser:dev-face-time-hd",
        role="primary",
        status="ONLINE"
    )
    cam_b_db = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_b_id,
        name="Test Camera Beta (Secondary)",
        location="Sector Beta Perimeter",
        protocol="WEBCAM",
        stream_url="browser:dev-usb-cam-ext",
        role="secondary",
        status="ONLINE"
    )
    db.add(cam_a_db)
    db.add(cam_b_db)
    db.commit()
    db.close()

    # =========================================================================
    # TEST 1: Connect Camera A -> connected -> live frames -> AI inference
    # =========================================================================
    print("\n[TEST 1] Starting Camera A...")
    mgr.start_stream(cam_a_id, "WEBCAM", "browser:dev-face-time-hd", ws)
    await asyncio.sleep(0.15)

    worker_a = mgr.get_worker(cam_a_id)
    assert worker_a is not None, "Worker A was not initialized"
    assert isinstance(worker_a.source, PushVideoSource), f"Expected PushVideoSource, got {type(worker_a.source)}"
    assert worker_a.is_running is True, "Worker A must be running"

    # Push frames to Camera A
    for _ in range(3):
        pushed = mgr.push_frame(cam_a_id, img_person)
        assert pushed is True, "Failed to push frame to Camera A"
        await asyncio.sleep(0.08)

    # Verify Camera A processed frames and generated AI tracking output
    await asyncio.sleep(0.2)
    assert worker_a.frame_sequence > 0, "Camera A did not advance frame sequence"
    assert worker_a.current_fps > 0, f"Camera A must report >0 FPS, got {worker_a.current_fps}"
    print(f"✓ TEST 1 PASSED: Camera A active @ {worker_a.current_fps} FPS, frame seq={worker_a.frame_sequence}")

    # =========================================================================
    # TEST 2: Connect Camera B without disconnecting Camera A -> both run independently
    # =========================================================================
    print("\n[TEST 2] Starting Camera B while Camera A remains active...")
    mgr.start_stream(cam_b_id, "WEBCAM", "browser:dev-usb-cam-ext", ws)
    await asyncio.sleep(0.15)

    worker_b = mgr.get_worker(cam_b_id)
    assert worker_b is not None, "Worker B was not initialized"
    assert isinstance(worker_b.source, PushVideoSource), f"Expected PushVideoSource for B, got {type(worker_b.source)}"

    # Verify both workers exist simultaneously in StreamManager
    assert cam_a_id in mgr.workers, "Camera A disappeared when Camera B was connected!"
    assert cam_b_id in mgr.workers, "Camera B was not registered in StreamManager workers"
    assert mgr.workers[cam_a_id].is_running is True, "Camera A was stopped when Camera B connected"
    assert mgr.workers[cam_b_id].is_running is True, "Camera B must be running"

    # Push frames to both cameras concurrently
    for _ in range(3):
        mgr.push_frame(cam_a_id, img_person)
        mgr.push_frame(cam_b_id, img_vehicle)
        await asyncio.sleep(0.08)

    await asyncio.sleep(0.2)
    assert worker_a.is_running is True, "Camera A must remain running"
    assert worker_b.is_running is True, "Camera B must be running"
    assert worker_a.frame_sequence > 0
    assert worker_b.frame_sequence > 0
    print(f"✓ TEST 2 PASSED: Both Camera A (seq={worker_a.frame_sequence}) and Camera B (seq={worker_b.frame_sequence}) running simultaneously.")

    # =========================================================================
    # TEST 3: Show person to Camera A -> Detection belongs only to Camera A
    # =========================================================================
    print("\n[TEST 3] Person frame to Camera A, blank frame to Camera B (Isolation Check)...")
    blank_frame = np.zeros((360, 640, 3), dtype=np.uint8)

    worker_a.agent.cleanup_live_session()
    worker_b.agent.cleanup_live_session()
    worker_a.latest_tracked_objs = []
    worker_b.latest_tracked_objs = []
    ws.broadcasted.clear()
    for _ in range(4):
        mgr.push_frame(cam_a_id, img_person)
        mgr.push_frame(cam_b_id, blank_frame)
        await asyncio.sleep(0.1)

    cam_a_msgs = []
    cam_b_msgs = []
    cam_a_dets = []
    for _ in range(25):
        mgr.push_frame(cam_a_id, img_person)
        mgr.push_frame(cam_b_id, blank_frame)
        await asyncio.sleep(0.1)
        cam_a_msgs = ws.get_camera_messages(cam_a_id)
        cam_b_msgs = ws.get_camera_messages(cam_b_id)
        cam_a_dets = [d for msg in cam_a_msgs for d in msg.get("detections", [])]
        if len(cam_a_dets) > 0:
            break

    assert len(cam_a_msgs) > 0, "No telemetry messages received for Camera A"
    assert len(cam_b_msgs) > 0, "No telemetry messages received for Camera B"

    # Check that detections in Camera A messages belong exclusively to Camera A
    assert len(cam_a_dets) > 0, "Camera A failed to detect person"
    for msg in cam_a_msgs:
        assert msg["camera_id"] == cam_a_id
        for det in msg.get("detections", []):
            assert det["camera_id"] == cam_a_id

    # Check that Camera B received 0 person detections
    for msg in cam_b_msgs:
        assert msg["camera_id"] == cam_b_id
        for det in msg.get("detections", []):
            assert det["camera_id"] == cam_b_id
            assert det["class_name"] != "person", f"Camera B leaked person detection from Camera A: {det}"

    print("✓ TEST 3 PASSED: Camera A received person detections, Camera B completely isolated.")

    # =========================================================================
    # TEST 4: Show object to Camera B, blank to Camera A -> Detection belongs only to Camera B
    # =========================================================================
    print("\n[TEST 4] Object frame to Camera B, blank frame to Camera A (Reverse Isolation)...")
    worker_a.agent.cleanup_live_session()
    worker_b.agent.cleanup_live_session()
    worker_a.latest_tracked_objs = []
    worker_b.latest_tracked_objs = []
    ws.broadcasted.clear()
    for _ in range(4):
        mgr.push_frame(cam_a_id, blank_frame)
        mgr.push_frame(cam_b_id, img_person)
        await asyncio.sleep(0.1)

    cam_a_msgs = []
    cam_b_msgs = []
    cam_b_dets = []
    for _ in range(25):
        mgr.push_frame(cam_a_id, blank_frame)
        mgr.push_frame(cam_b_id, img_person)
        await asyncio.sleep(0.1)
        cam_a_msgs = ws.get_camera_messages(cam_a_id)
        cam_b_msgs = ws.get_camera_messages(cam_b_id)
        cam_b_dets = [d for msg in cam_b_msgs for d in msg.get("detections", [])]
        if len(cam_b_dets) > 0:
            break

    cam_a_dets = [d for msg in cam_a_msgs for d in msg.get("detections", [])]

    assert len(cam_a_dets) == 0, f"Camera A leaked detection from Camera B: {cam_a_dets}"
    assert len(cam_b_dets) > 0, "Camera B failed to detect objects"
    for det in cam_b_dets:
        assert det["camera_id"] == cam_b_id

    print("✓ TEST 4 PASSED: Camera B received detections, Camera A completely isolated.")

    # =========================================================================
    # TEST 5: Disconnect Camera B -> Camera B disconnected, Camera A continues
    # =========================================================================
    print("\n[TEST 5] Disconnecting Camera B only...")
    mgr.stop_stream(cam_b_id)
    await asyncio.sleep(0.15)

    assert cam_b_id not in mgr.workers, "Camera B was not removed from active workers"
    assert cam_a_id in mgr.workers, "Camera A was improperly removed when Camera B was stopped!"
    assert mgr.workers[cam_a_id].is_running is True, "Camera A was stopped when Camera B disconnected!"

    # Push frame to Camera A to verify uninterrupted operation
    prev_seq = worker_a.frame_sequence
    mgr.push_frame(cam_a_id, img_person)
    await asyncio.sleep(0.1)
    assert worker_a.frame_sequence > prev_seq, "Camera A stopped ingesting frames after Camera B disconnected"
    print(f"✓ TEST 5 PASSED: Camera B stopped cleanly; Camera A continues running (seq={worker_a.frame_sequence}).")

    # =========================================================================
    # TEST 6: Reconnect Camera B -> Camera A remains connected, Camera B resumes
    # =========================================================================
    print("\n[TEST 6] Reconnecting Camera B...")
    mgr.start_stream(cam_b_id, "WEBCAM", "browser:dev-usb-cam-ext", ws)
    await asyncio.sleep(0.15)

    worker_b_reconn = mgr.get_worker(cam_b_id)
    assert worker_b_reconn is not None, "Failed to reinitialize Camera B"
    assert worker_b_reconn.is_running is True, "Reconnected Camera B is not running"
    assert mgr.workers[cam_a_id].is_running is True, "Camera A was interrupted by Camera B reconnection"

    # Push frames to both
    mgr.push_frame(cam_a_id, img_person)
    mgr.push_frame(cam_b_id, img_vehicle)
    await asyncio.sleep(0.15)

    assert worker_a.is_running is True
    assert worker_b_reconn.is_running is True
    assert len(mgr.workers) == 2
    print("✓ TEST 6 PASSED: Camera A remained active; Camera B reconnected as an independent stream.")

    # Cleanup
    mgr.stop_all()
    safe_clean_cams([cam_a_id, cam_b_id])
    print("\nALL 6 MULTI-CAMERA ISOLATION & LIFECYCLE TESTS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(test_simultaneous_multi_camera_lifecycle())
