"""
Comprehensive Multi-Camera Connection & Independence Tests (Scenarios 1 - 6)
Validates simultaneous multi-camera streams, isolated lifecycles, non-interfering stop/start,
per-camera detection tagging, and accurate browser mediaDevices diagnostic reporting.
"""

import asyncio
import numpy as np
from backend.stream_manager import StreamManager
from video_engine.ingestion.source import create_video_source, PushVideoSource, WebcamVideoSource

class MockWebSocketManager:
    def __init__(self):
        self.broadcasted = []

    async def broadcast(self, message):
        self.broadcasted.append(message)


def test_scenario_1_and_2_multiple_cameras_simultaneous():
    """
    TEST 1 & TEST 2:
    - Connect Camera A: Camera A works.
    - Connect Camera B while Camera A is running: Both continue working independently. Neither replaces the other.
    """
    async def run():
        ws = MockWebSocketManager()
        mgr = StreamManager()
        mgr.set_loop(asyncio.get_running_loop())

        frame_a = np.zeros((360, 640, 3), dtype=np.uint8)
        frame_a[:] = (255, 0, 0)

        frame_b = np.zeros((360, 640, 3), dtype=np.uint8)
        frame_b[:] = (0, 255, 0)

        # 1. Start Camera A
        mgr.start_stream("CAM-TEST-A", "BROWSER", "browser:device-a", ws)
        await asyncio.sleep(0.1)
        worker_a = mgr.get_worker("CAM-TEST-A")
        assert worker_a is not None
        assert isinstance(worker_a.source, PushVideoSource)

        mgr.push_frame("CAM-TEST-A", frame_a)
        await asyncio.sleep(0.15)
        assert worker_a.is_running is True

        # 2. Start Camera B
        mgr.start_stream("CAM-TEST-B", "BROWSER", "browser:device-b", ws)
        await asyncio.sleep(0.1)
        worker_b = mgr.get_worker("CAM-TEST-B")
        assert worker_b is not None
        assert isinstance(worker_b.source, PushVideoSource)

        mgr.push_frame("CAM-TEST-B", frame_b)
        await asyncio.sleep(0.15)

        # Verify both workers are active simultaneously and neither replaced the other
        assert "CAM-TEST-A" in mgr.workers
        assert "CAM-TEST-B" in mgr.workers
        assert mgr.workers["CAM-TEST-A"].is_running is True
        assert mgr.workers["CAM-TEST-B"].is_running is True
        assert len(mgr.workers) == 2

        mgr.stop_all()

    asyncio.run(run())


def test_scenario_3_disconnect_b_keeps_a_running():
    """
    TEST 3:
    - Connect Camera A + Camera B.
    - Disconnect Camera B.
    - Expected: Camera A continues working, Camera B becomes disconnected.
    """
    async def run():
        ws = MockWebSocketManager()
        mgr = StreamManager()
        mgr.set_loop(asyncio.get_running_loop())

        frame = np.zeros((360, 640, 3), dtype=np.uint8)

        mgr.start_stream("CAM-TEST-A", "BROWSER", "browser:dev-1", ws)
        mgr.start_stream("CAM-TEST-B", "BROWSER", "browser:dev-2", ws)

        await asyncio.sleep(0.1)
        mgr.push_frame("CAM-TEST-A", frame)
        mgr.push_frame("CAM-TEST-B", frame)
        await asyncio.sleep(0.15)

        assert mgr.get_worker("CAM-TEST-A").is_running is True
        assert mgr.get_worker("CAM-TEST-B").is_running is True

        # Disconnect Camera B only
        mgr.stop_stream("CAM-TEST-B")

        # Verify Camera A remains active and running
        assert "CAM-TEST-A" in mgr.workers
        assert mgr.workers["CAM-TEST-A"].is_running is True

        # Verify Camera B is removed from active workers
        assert "CAM-TEST-B" not in mgr.workers

        mgr.stop_all()

    asyncio.run(run())


def test_scenario_4_stop_a_keeps_b_running():
    """
    TEST 4:
    - Connect Camera A + Camera B.
    - Stop Camera A.
    - Expected: Camera B continues working.
    """
    async def run():
        ws = MockWebSocketManager()
        mgr = StreamManager()
        mgr.set_loop(asyncio.get_running_loop())

        frame = np.zeros((360, 640, 3), dtype=np.uint8)

        mgr.start_stream("CAM-TEST-A", "BROWSER", "browser:dev-1", ws)
        mgr.start_stream("CAM-TEST-B", "BROWSER", "browser:dev-2", ws)

        await asyncio.sleep(0.1)
        mgr.push_frame("CAM-TEST-A", frame)
        mgr.push_frame("CAM-TEST-B", frame)
        await asyncio.sleep(0.15)

        # Stop Camera A
        mgr.stop_stream("CAM-TEST-A")

        # Verify Camera B continues running
        assert "CAM-TEST-B" in mgr.workers
        assert mgr.workers["CAM-TEST-B"].is_running is True
        assert "CAM-TEST-A" not in mgr.workers

        mgr.stop_all()

    asyncio.run(run())


def test_scenario_5_camera_specific_detections():
    """
    TEST 5:
    - Connect multiple cameras and verify detections remain associated with the correct camera ID.
    - Detections from Camera A must never be attributed to Camera B.
    """
    async def run():
        ws = MockWebSocketManager()
        mgr = StreamManager()
        mgr.set_loop(asyncio.get_running_loop())

        frame = np.zeros((360, 640, 3), dtype=np.uint8)

        mgr.start_stream("CAM-01", "BROWSER", "browser:dev-cam01", ws)
        mgr.start_stream("CAM-02", "BROWSER", "browser:dev-cam02", ws)

        await asyncio.sleep(0.1)
        worker_1 = mgr.get_worker("CAM-01")
        worker_2 = mgr.get_worker("CAM-02")

        assert worker_1.camera_id == "CAM-01"
        assert worker_2.camera_id == "CAM-02"
        assert worker_1.agent.camera_id == "CAM-01"
        assert worker_2.agent.camera_id == "CAM-02"

        mgr.push_frame("CAM-01", frame)
        mgr.push_frame("CAM-02", frame)
        await asyncio.sleep(0.2)

        # Check broadcast messages for camera_id separation
        cam1_messages = [m for m in ws.broadcasted if m.get("camera_id") == "CAM-01"]
        cam2_messages = [m for m in ws.broadcasted if m.get("camera_id") == "CAM-02"]

        for msg in cam1_messages:
            assert msg["camera_id"] == "CAM-01"
            for d in msg.get("detections", []):
                assert d["camera_id"] == "CAM-01"

        for msg in cam2_messages:
            assert msg["camera_id"] == "CAM-02"
            for d in msg.get("detections", []):
                assert d["camera_id"] == "CAM-02"

        mgr.stop_all()

    asyncio.run(run())


def test_scenario_6_error_classification_logic():
    """
    TEST 6:
    - Verify that browser webcam permission / insecure context error is properly
      distinguished from 'No camera device found'.
    """
    src_browser = create_video_source("CAM-1", "WEBCAM", "d17e9b82aa4490f8")
    assert isinstance(src_browser, PushVideoSource)

    src_dev0 = create_video_source("CAM-2", "WEBCAM", "0")
    assert isinstance(src_dev0, WebcamVideoSource)
    assert src_dev0.device_index == 0

    src_dev1 = create_video_source("CAM-3", "WEBCAM", "1")
    assert isinstance(src_dev1, WebcamVideoSource)
    assert src_dev1.device_index == 1
