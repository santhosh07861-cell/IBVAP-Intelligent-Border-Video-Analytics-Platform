import asyncio
import os
import time
import pytest
from unittest.mock import patch
from database.connection import SessionLocal
from database.schema import Camera, CameraHealth, User
from backend.routers.camera_router import (
    normalize_camera_url,
    diagnose_stream_connection,
    test_connection as api_test_connection,
    start_camera,
    TestConnectionRequest as ApiTestConnectionRequest
)
from backend.stream_manager import stream_manager

def test_custom_url_preservation():
    """Verify custom stream URL endpoints are never clobbered or forcibly appended with /video."""
    url1, src1 = normalize_camera_url("http://10.179.43.18:8080/mjpegfeed", "RTSP")
    assert url1 == "http://10.179.43.18:8080/mjpegfeed", f"URL was modified: {url1}"

    url2, src2 = normalize_camera_url("http://10.179.43.18:8080/live", "RTSP")
    assert url2 == "http://10.179.43.18:8080/live", f"URL was modified: {url2}"

    url3, src3 = normalize_camera_url("rtsp://10.179.43.18:8554/stream1", "RTSP")
    assert url3 == "rtsp://10.179.43.18:8554/stream1", f"URL was modified: {url3}"

    url4, src4 = normalize_camera_url("http://10.179.43.18:8080", "RTSP")
    assert url4 == "http://10.179.43.18:8080/video", f"Root URL did not receive default path: {url4}"


def test_diagnose_host_unreachable_same_subnet():
    """Verify diagnostic accurately identifies same-subnet AP isolation / sleeping radio when server is on 10.179.43.80."""
    with patch("backend.routers.camera_router.get_local_server_ip", return_value="10.179.43.80"):
        err_type, msg = diagnose_stream_connection("http://10.179.43.18:8080/video", "10.179.43.18", 8080, err_code=65)
        assert err_type == "HOST_UNREACHABLE"
        assert "No route to host" in msg
        assert "10.179.43.18" in msg
        assert "Router AP/Client Isolation" in msg
        assert "Mobile Hotspot" in msg


def test_diagnose_host_unreachable_subnet_mismatch():
    """Verify diagnostic accurately identifies subnet mismatch when server is on a different subnet."""
    with patch("backend.routers.camera_router.get_local_server_ip", return_value="192.168.1.14"):
        err_type, msg = diagnose_stream_connection("http://10.179.43.18:8080/video", "10.179.43.18", 8080, err_code=65)
        assert err_type == "HOST_UNREACHABLE"
        assert "Network Subnet Mismatch" in msg
        assert "192.168.1.14" in msg
        assert "10.179.43.18" in msg


def test_diagnose_connection_refused():
    """Verify diagnostic accurately identifies closed port / app not running."""
    err_type, msg = diagnose_stream_connection("http://127.0.0.1:19999/video", "127.0.0.1", 19999, err_code=61)
    assert err_type == "CONNECTION_REFUSED"
    assert "Connection refused" in msg
    assert "port 19999 is closed" in msg
    assert "app" in msg.lower()


def test_diagnose_invalid_port():
    """Verify invalid port range is caught."""
    err_type, msg = diagnose_stream_connection("http://10.179.43.18:70000/video", "10.179.43.18", 70000)
    assert err_type == "INVALID_PORT"
    assert "70000" in msg


def test_real_test_connection_endpoint_host_unreachable():
    """Verify /api/cameras/test-connection performs real network check and returns detailed diagnostic."""
    req = ApiTestConnectionRequest(protocol="RTSP", stream_url="http://10.179.43.18:8080/video")
    mock_user = type("MockUser", (), {"username": "admin", "role": "Administrator"})()
    res = api_test_connection(req, current_user=mock_user)

    assert res["connected"] is False
    assert res["status"] == "FAILED"
    assert res["error_type"] in ["HOST_UNREACHABLE", "CONNECTION_TIMEOUT", "NETWORK_ERROR"]
    assert res["fps"] == 0.0
    assert "10.179.43.18" in res["message"]
    assert res["camera_ip"] == "10.179.43.18"


def test_multi_camera_simultaneous_independence():
    """
    CRITICAL REQUIREMENT:
    CAMERA A connects and is ONLINE.
    CAMERA B connects to 10.179.43.18:8080 and reports UNREACHABLE.
    CAMERA A must remain ONLINE and streaming frames without any interruption or clobbering.
    """
    async def _test_async():
        db = SessionLocal()
        cam_a_id = "CAM-TEST-A"
        cam_b_id = "CAM-TEST-B"

        # Clean previous test entries
        db.query(Camera).filter(Camera.camera_id.in_([cam_a_id, cam_b_id])).delete(synchronize_session=False)
        db.commit()

        # Create Camera A (MP4 continuous surveillance source)
        video_path = "storage/demo_videos/border_patrol.mp4"
        cam_a = Camera(
            camera_id=cam_a_id,
            name="Camera A Test",
            stream_url=video_path,
            protocol="MP4",
            role="primary",
            status="OFFLINE"
        )
        db.add(cam_a)
        health_a = CameraHealth(camera_id=cam_a.id, status="OFFLINE")
        db.add(health_a)

        # Create Camera B (Unreachable network IP camera 10.179.43.18:8080)
        cam_b = Camera(
            camera_id=cam_b_id,
            name="Camera B Test",
            stream_url="http://10.179.43.18:8080/video",
            protocol="RTSP",
            role="secondary",
            status="OFFLINE"
        )
        db.add(cam_b)
        health_b = CameraHealth(camera_id=cam_b.id, status="OFFLINE")
        db.add(health_b)
        db.commit()

        mock_user = type("MockUser", (), {"username": "admin", "role": "Administrator"})()

        try:
            # Subscribe test client so stream encodes JPEG
            stream_manager.subscribe(cam_a_id, "test_client_sub")

            # 1. Start Camera A
            res_a = await start_camera(cam_a_id, db=db, current_user=mock_user)
            assert res_a["status"] == "success"

            # Give Camera A 1.0s to ingest initial frames
            await asyncio.sleep(1.0)

            worker_a = stream_manager.get_worker(cam_a_id)
            assert worker_a is not None, "Worker A was not registered"
            assert worker_a.is_running is True, "Worker A is not running"

            db.refresh(cam_a)
            assert cam_a.status == "ONLINE", f"Camera A status is {cam_a.status}, expected ONLINE"
            assert worker_a.frame_sequence > 0, "Camera A did not ingest frames"

            jpeg_a1 = worker_a.get_latest_jpeg()
            assert jpeg_a1 is not None, "Camera A did not produce JPEG frames"

            # 2. Now start Camera B (10.179.43.18:8080)
            res_b = await start_camera(cam_b_id, db=db, current_user=mock_user)
            assert res_b["status"] == "unreachable", f"Expected unreachable, got {res_b['status']}"
            assert "unreachable" in res_b["message"].lower()

            # 3. VERIFY CAMERA A IS STILL ONLINE AND WORKING PERFECTLY!
            assert worker_a.is_running is True, "Worker A was terminated when Camera B started!"
            worker_a_after = stream_manager.get_worker(cam_a_id)
            assert worker_a_after is worker_a, "Worker A was replaced or overwritten!"

            db.refresh(cam_a)
            assert cam_a.status == "ONLINE", f"Camera A status changed to {cam_a.status}!"

            jpeg_a2 = worker_a.get_latest_jpeg()
            assert jpeg_a2 is not None, "Camera A frame buffer was destroyed!"

            # 4. VERIFY CAMERA B IS INDEPENDENTLY MANAGED
            worker_b = stream_manager.get_worker(cam_b_id)
            assert worker_b is not None, "Worker B background retry worker was not registered!"
            assert worker_b is not worker_a, "Worker B is reusing Worker A's instance!"

            db.refresh(cam_b)
            assert cam_b.status == "UNREACHABLE", f"Camera B status should be UNREACHABLE, got {cam_b.status}"
            assert cam_b.fps == 0.0, f"Camera B must have 0 FPS when unreachable, got {cam_b.fps}"

        finally:
            stream_manager.stop_stream(cam_a_id)
            stream_manager.stop_stream(cam_b_id)
            db.query(Camera).filter(Camera.camera_id.in_([cam_a_id, cam_b_id])).delete(synchronize_session=False)
            db.commit()
            db.close()

    asyncio.run(_test_async())
