"""
End-to-End Test Suite: Multi-Camera Independent Streaming & Connection Isolation
================================================================================
Validates:
1. Simultaneous independent streaming of IP camera + MacBook webcam without mutual interference.
2. Dynamic addition and startup of Camera B while Camera A is actively streaming with zero disruption to Camera A.
3. Stopping Camera B while Camera A continues streaming without frame drops or status corruption.
4. Dynamic PRIMARY / SECONDARY role assignment changes without interrupting or restarting active streams.
5. Immediate browser push-frame delivery to WebcamVideoSource queue without hardware lock contention.
6. Genuine status reporting (ONLINE, STOPPED, CONNECTING, NO_FRAMES) and strict non-mock camera ID preservation.
"""

import asyncio
import uuid
import time
import numpy as np
import pytest
from sqlalchemy import text

from database.connection import SessionLocal, engine
from database.schema import Camera
from backend.stream_manager import StreamManager
from video_engine.ingestion.source import WebcamVideoSource, PushVideoSource


class MockBroadcastHub:
    def __init__(self):
        self.messages = []
        self._lock = asyncio.Lock()

    async def broadcast(self, message: dict):
        async with self._lock:
            self.messages.append(message)

    def get_messages(self, camera_id: str):
        return [m for m in self.messages if m.get("camera_id") == camera_id]


def clean_test_cameras(camera_ids: list):
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        for table in [
            "camera_zones", "camera_health", "detections", "tracks",
            "face_detections", "behavior_events", "anpr_results",
            "evidence", "alerts", "incidents", "events"
        ]:
            for cid in camera_ids:
                conn.execute(
                    text(f"DELETE FROM {table} WHERE camera_id = :cid OR camera_id IN (SELECT id FROM cameras WHERE camera_id = :cid)"),
                    {"cid": cid}
                )
        for cid in camera_ids:
            conn.execute(text("DELETE FROM cameras WHERE camera_id = :cid"), {"cid": cid})
        conn.execute(text("PRAGMA foreign_keys = ON"))


@pytest.mark.anyio
async def test_simultaneous_ip_and_webcam_streaming_independence():
    """Test 1: IP Camera and Webcam run simultaneously and independently without interference."""
    ws = MockBroadcastHub()
    mgr = StreamManager()
    mgr.set_loop(asyncio.get_running_loop())

    cam_ip_id = f"CAM-IP-{uuid.uuid4().hex[:6].upper()}"
    cam_webcam_id = f"CAM-WEBCAM-{uuid.uuid4().hex[:6].upper()}"
    clean_test_cameras([cam_ip_id, cam_webcam_id])

    db = SessionLocal()
    c1 = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_ip_id,
        name="Perimeter Mobile IP Camera",
        location="Sector Alpha South",
        protocol="RTSP",
        stream_url="http://10.179.43.18:8080/video",
        role="primary",
        status="ONLINE"
    )
    c2 = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_webcam_id,
        name="MacBook Built-in FaceTime HD",
        location="Command Post Station 1",
        protocol="WEBCAM",
        stream_url="0",
        role="secondary",
        status="ONLINE"
    )
    db.add_all([c1, c2])
    db.commit()
    db.close()

    try:
        # Start both streams concurrently
        mgr.start_stream(cam_ip_id, "RTSP", "push:mock_ip", ws)
        mgr.start_stream(cam_webcam_id, "WEBCAM", "0", ws)

        # Allow workers to initialize
        for _ in range(20):
            w1 = mgr.get_worker(cam_ip_id)
            w2 = mgr.get_worker(cam_webcam_id)
            if w1 and w2 and w1.source is not None and w2.source is not None:
                break
            await asyncio.sleep(0.05)

        worker_ip = mgr.get_worker(cam_ip_id)
        worker_webcam = mgr.get_worker(cam_webcam_id)

        assert worker_ip is not None, "IP Camera worker was not created"
        assert worker_webcam is not None, "Webcam worker was not created"
        assert worker_ip.is_running is True, "IP Camera worker should be running"
        assert worker_webcam.is_running is True, "Webcam worker should be running"

        # Verify WebcamVideoSource was instantiated for cam_webcam_id
        assert isinstance(worker_webcam.source, WebcamVideoSource), (
            f"Expected WebcamVideoSource, got {type(worker_webcam.source)}"
        )

        # Create distinct test frames
        frame_ip = np.zeros((360, 640, 3), dtype=np.uint8)
        frame_ip[:, :] = (120, 40, 20)  # Distinct tint
        frame_webcam = np.zeros((360, 640, 3), dtype=np.uint8)
        frame_webcam[:, :] = (20, 120, 40)  # Distinct tint

        # Push frames into both cameras concurrently
        for _ in range(5):
            mgr.push_frame(cam_ip_id, frame_ip)
            mgr.push_frame(cam_webcam_id, frame_webcam)
            await asyncio.sleep(0.06)

        await asyncio.sleep(0.25)

        # Verify both cameras advanced their frame sequences independently
        assert worker_ip.frame_sequence > 0, "IP Camera did not advance frame sequence"
        assert worker_webcam.frame_sequence > 0, "Webcam did not advance frame sequence"
        assert worker_ip.current_fps > 0, f"IP Camera should report >0 FPS, got {worker_ip.current_fps}"
        assert worker_webcam.current_fps > 0, f"Webcam should report >0 FPS, got {worker_webcam.current_fps}"

        # Verify JPEG endpoints have real encoded frames for both cameras
        assert worker_ip.latest_jpeg is not None, "IP Camera latest_jpeg was not generated"
        assert worker_webcam.latest_jpeg is not None, "Webcam latest_jpeg was not generated"
        assert worker_ip.latest_jpeg.startswith(b"\xff\xd8"), "Invalid JPEG header on IP camera"
        assert worker_webcam.latest_jpeg.startswith(b"\xff\xd8"), "Invalid JPEG header on Webcam"

    finally:
        mgr.stop_stream(cam_ip_id)
        mgr.stop_stream(cam_webcam_id)
        clean_test_cameras([cam_ip_id, cam_webcam_id])


@pytest.mark.anyio
async def test_add_second_camera_does_not_interrupt_first():
    """Test 2: Adding and starting a second camera does not interrupt the first streaming camera."""
    ws = MockBroadcastHub()
    mgr = StreamManager()
    mgr.set_loop(asyncio.get_running_loop())

    cam_1_id = f"CAM-1-{uuid.uuid4().hex[:6].upper()}"
    cam_2_id = f"CAM-2-{uuid.uuid4().hex[:6].upper()}"
    clean_test_cameras([cam_1_id, cam_2_id])

    db = SessionLocal()
    c1 = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_1_id,
        name="Primary Camera Feed",
        location="Sector 1",
        protocol="RTSP",
        stream_url="push:cam1",
        role="primary",
        status="ONLINE"
    )
    c2 = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_2_id,
        name="Secondary Camera Feed",
        location="Sector 2",
        protocol="WEBCAM",
        stream_url="0",
        role="secondary",
        status="ONLINE"
    )
    db.add_all([c1, c2])
    db.commit()
    db.close()

    try:
        # Start Camera 1 first
        mgr.start_stream(cam_1_id, "RTSP", "push:cam1", ws)
        for _ in range(15):
            w1 = mgr.get_worker(cam_1_id)
            if w1 and w1.source is not None:
                break
            await asyncio.sleep(0.04)

        worker_1 = mgr.get_worker(cam_1_id)
        assert worker_1 is not None and worker_1.is_running is True

        dummy = np.zeros((240, 320, 3), dtype=np.uint8)
        for _ in range(4):
            mgr.push_frame(cam_1_id, dummy)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.15)
        seq_before_adding_c2 = worker_1.frame_sequence
        assert seq_before_adding_c2 > 0, "Camera 1 should have processed initial frames"

        # Now start Camera 2 while Camera 1 is actively streaming
        mgr.start_stream(cam_2_id, "WEBCAM", "0", ws)
        for _ in range(15):
            w2 = mgr.get_worker(cam_2_id)
            if w2 and w2.source is not None:
                break
            await asyncio.sleep(0.04)

        worker_2 = mgr.get_worker(cam_2_id)
        assert worker_2 is not None and worker_2.is_running is True

        # Continue pushing to Camera 1 and push to Camera 2
        for _ in range(4):
            mgr.push_frame(cam_1_id, dummy)
            mgr.push_frame(cam_2_id, dummy)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.2)

        # Verify Camera 1 never stopped and continued advancing
        assert worker_1.is_running is True, "Camera 1 was stopped when Camera 2 was added"
        assert worker_1.frame_sequence > seq_before_adding_c2, (
            f"Camera 1 frame sequence stalled ({worker_1.frame_sequence} <= {seq_before_adding_c2})"
        )
        assert worker_2.frame_sequence > 0, "Camera 2 did not start processing frames"

    finally:
        mgr.stop_stream(cam_1_id)
        mgr.stop_stream(cam_2_id)
        clean_test_cameras([cam_1_id, cam_2_id])


@pytest.mark.anyio
async def test_stop_second_camera_keeps_first_streaming():
    """Test 3: Stopping Camera 2 does not affect Camera 1 in any way."""
    ws = MockBroadcastHub()
    mgr = StreamManager()
    mgr.set_loop(asyncio.get_running_loop())

    cam_1_id = f"CAM-ALPHA-{uuid.uuid4().hex[:6].upper()}"
    cam_2_id = f"CAM-BETA-{uuid.uuid4().hex[:6].upper()}"
    clean_test_cameras([cam_1_id, cam_2_id])

    db = SessionLocal()
    c1 = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_1_id,
        name="Alpha Feed",
        location="Sector Alpha",
        protocol="RTSP",
        stream_url="push:cam_alpha",
        role="primary",
        status="ONLINE"
    )
    c2 = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_2_id,
        name="Beta Feed",
        location="Sector Beta",
        protocol="WEBCAM",
        stream_url="0",
        role="secondary",
        status="ONLINE"
    )
    db.add_all([c1, c2])
    db.commit()
    db.close()

    try:
        mgr.start_stream(cam_1_id, "RTSP", "push:cam_alpha", ws)
        mgr.start_stream(cam_2_id, "WEBCAM", "0", ws)

        for _ in range(20):
            w1 = mgr.get_worker(cam_1_id)
            w2 = mgr.get_worker(cam_2_id)
            if w1 and w2 and w1.source is not None and w2.source is not None:
                break
            await asyncio.sleep(0.04)

        worker_1 = mgr.get_worker(cam_1_id)
        worker_2 = mgr.get_worker(cam_2_id)
        assert worker_1.is_running is True
        assert worker_2.is_running is True

        dummy = np.zeros((240, 320, 3), dtype=np.uint8)
        for _ in range(4):
            mgr.push_frame(cam_1_id, dummy)
            mgr.push_frame(cam_2_id, dummy)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.15)
        seq_c1_before_stop = worker_1.frame_sequence

        # Stop Camera 2
        mgr.stop_stream(cam_2_id)
        await asyncio.sleep(0.15)

        # Verify Camera 2 worker is terminated
        assert cam_2_id not in mgr.workers or mgr.workers[cam_2_id].is_running is False

        # Verify Camera 1 is still completely active
        assert worker_1.is_running is True, "Camera 1 unexpectedly stopped when Camera 2 was stopped"

        # Continue streaming to Camera 1
        for _ in range(4):
            mgr.push_frame(cam_1_id, dummy)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.15)
        assert worker_1.frame_sequence > seq_c1_before_stop, (
            f"Camera 1 stalled after stopping Camera 2 ({worker_1.frame_sequence} <= {seq_c1_before_stop})"
        )

    finally:
        mgr.stop_stream(cam_1_id)
        mgr.stop_stream(cam_2_id)
        clean_test_cameras([cam_1_id, cam_2_id])


@pytest.mark.anyio
async def test_primary_secondary_role_switch_does_not_disrupt_streams():
    """Test 4: Changing primary / secondary designation does not restart or disrupt either stream."""
    ws = MockBroadcastHub()
    mgr = StreamManager()
    mgr.set_loop(asyncio.get_running_loop())

    cam_a_id = f"CAM-ROLE-A-{uuid.uuid4().hex[:6].upper()}"
    cam_b_id = f"CAM-ROLE-B-{uuid.uuid4().hex[:6].upper()}"
    clean_test_cameras([cam_a_id, cam_b_id])

    db = SessionLocal()
    c_a = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_a_id,
        name="Role Test Camera A",
        location="Gate A",
        protocol="RTSP",
        stream_url="push:cam_role_a",
        role="primary",
        status="ONLINE"
    )
    c_b = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_b_id,
        name="Role Test Camera B",
        location="Gate B",
        protocol="WEBCAM",
        stream_url="0",
        role="secondary",
        status="ONLINE"
    )
    db.add_all([c_a, c_b])
    db.commit()
    db.close()

    try:
        mgr.start_stream(cam_a_id, "RTSP", "push:cam_role_a", ws)
        mgr.start_stream(cam_b_id, "WEBCAM", "0", ws)

        for _ in range(20):
            w1 = mgr.get_worker(cam_a_id)
            w2 = mgr.get_worker(cam_b_id)
            if w1 and w2 and w1.source is not None and w2.source is not None:
                break
            await asyncio.sleep(0.04)

        worker_a = mgr.get_worker(cam_a_id)
        worker_b = mgr.get_worker(cam_b_id)

        dummy = np.zeros((240, 320, 3), dtype=np.uint8)
        for _ in range(3):
            mgr.push_frame(cam_a_id, dummy)
            mgr.push_frame(cam_b_id, dummy)
            await asyncio.sleep(0.05)

        # Perform logical role swap in DB (simulating POST /api/cameras/{id}/set-primary)
        db = SessionLocal()
        db_cam_a = db.query(Camera).filter(Camera.camera_id == cam_a_id).first()
        db_cam_b = db.query(Camera).filter(Camera.camera_id == cam_b_id).first()
        db_cam_a.role = "secondary"
        db_cam_b.role = "primary"
        db.commit()
        db.close()

        # Verify neither worker was killed or recreated
        assert worker_a.is_running is True, "Worker A was disrupted by role change"
        assert worker_b.is_running is True, "Worker B was disrupted by role change"

        # Verify both continue accepting frames smoothly
        for _ in range(3):
            mgr.push_frame(cam_a_id, dummy)
            mgr.push_frame(cam_b_id, dummy)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.15)
        assert worker_a.frame_sequence > 3
        assert worker_b.frame_sequence > 3

    finally:
        mgr.stop_stream(cam_a_id)
        mgr.stop_stream(cam_b_id)
        clean_test_cameras([cam_a_id, cam_b_id])


@pytest.mark.anyio
async def test_webcam_push_frame_buffer_before_worker_ready():
    """Test 5: Browser webcam frames pushed before worker source creation are buffered and delivered."""
    ws = MockBroadcastHub()
    mgr = StreamManager()
    mgr.set_loop(asyncio.get_running_loop())

    cam_id = f"CAM-BUF-{uuid.uuid4().hex[:6].upper()}"
    clean_test_cameras([cam_id])

    db = SessionLocal()
    cam = Camera(
        id=str(uuid.uuid4()),
        camera_id=cam_id,
        name="Buffer Test Webcam",
        location="Station",
        protocol="WEBCAM",
        stream_url="0",
        role="secondary",
        status="ONLINE"
    )
    db.add(cam)
    db.commit()
    db.close()

    try:
        # Start stream
        mgr.start_stream(cam_id, "WEBCAM", "0", ws)
        worker = mgr.get_worker(cam_id)
        assert worker is not None

        # Push frame immediately (even before background source creation finishes)
        dummy = np.zeros((240, 320, 3), dtype=np.uint8)
        pushed = mgr.push_frame(cam_id, dummy)
        assert pushed is True, "Frame pushed before worker ready should be accepted into buffer"

        # Wait for worker source creation to complete
        for _ in range(25):
            if worker.source is not None and isinstance(worker.source, WebcamVideoSource):
                break
            await asyncio.sleep(0.04)

        assert worker.source is not None, "Worker source was not initialized"

        # Push additional frames
        for _ in range(3):
            mgr.push_frame(cam_id, dummy)
            await asyncio.sleep(0.06)

        await asyncio.sleep(0.2)
        assert worker.frame_sequence > 0, "Buffered and subsequent frames were not ingested"

    finally:
        mgr.stop_stream(cam_id)
        clean_test_cameras([cam_id])


@pytest.mark.anyio
async def test_genuine_status_reporting_and_non_mock_camera_id():
    """Test 6: Genuine status reporting in WS payloads (ONLINE with fps > 0, STOPPED upon stop) and real IDs."""
    ws = MockBroadcastHub()
    mgr = StreamManager()
    mgr.set_loop(asyncio.get_running_loop())

    real_camera_id = f"CAM-{uuid.uuid4().hex[:6].upper()}"
    clean_test_cameras([real_camera_id])

    db = SessionLocal()
    c = Camera(
        id=str(uuid.uuid4()),
        camera_id=real_camera_id,
        name="Authentic Surveillance Camera",
        location="Sector Charlie Perimeter",
        protocol="WEBCAM",
        stream_url="0",
        role="primary",
        status="ONLINE"
    )
    db.add(c)
    db.commit()
    db.close()

    try:
        mgr.start_stream(real_camera_id, "WEBCAM", "0", ws)
        for _ in range(20):
            w = mgr.get_worker(real_camera_id)
            if w and w.source is not None:
                break
            await asyncio.sleep(0.04)

        dummy = np.zeros((240, 320, 3), dtype=np.uint8)
        for _ in range(5):
            mgr.push_frame(real_camera_id, dummy)
            await asyncio.sleep(0.06)

        await asyncio.sleep(0.25)

        # Inspect broadcasted telemetry messages
        msgs = ws.get_messages(real_camera_id)
        assert len(msgs) > 0, f"Expected telemetry messages for {real_camera_id}"

        for m in msgs:
            assert m["camera_id"] == real_camera_id, f"Fake camera ID leaked: {m['camera_id']}"
            assert m["camera_id"] not in ["1", "2", "3", "cam1", "cam2"], "Mock numeric camera ID detected!"
            # Verify status is ONLINE when FPS > 0
            if m.get("fps", 0) > 0:
                assert m.get("status") == "ONLINE", f"Expected ONLINE status with real FPS, got {m.get('status')}"

        # Now stop the stream and verify STOPPED message is broadcasted
        mgr.stop_stream(real_camera_id)
        await asyncio.sleep(0.15)

        stopped_msgs = [m for m in ws.get_messages(real_camera_id) if m.get("status") == "STOPPED"]
        assert len(stopped_msgs) > 0, "No STOPPED status broadcasted when worker stopped"
        assert stopped_msgs[-1]["fps"] == 0.0, "Stopped status must report 0.0 FPS"

    finally:
        mgr.stop_stream(real_camera_id)
        clean_test_cameras([real_camera_id])
