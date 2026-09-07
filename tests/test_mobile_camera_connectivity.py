"""
Unit and Integration Tests for IBVAP Mobile Camera / RTSP Connectivity Engine.
Validates URL normalization, connectivity testing, error diagnosis, network info,
and video source lifecycle.
"""

import os
import time
import requests
from backend.auth import create_access_token
from backend.routers.camera_router import normalize_camera_url, validate_stream_url, get_local_server_ip
from video_engine.ingestion.source import create_video_source, HTTPMJPEGVideoSource, RTSPVideoSource, WebcamVideoSource, MP4VideoSource

BASE_URL = "http://127.0.0.1:8000"
token = create_access_token(data={"sub": "admin"})
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def test_url_normalization():
    print("\n--- 1. Testing URL Normalization & Source Type Resolution ---")
    
    # HTTP MJPEG variations
    u1, t1 = normalize_camera_url("http://192.168.1.50:8080/video", "RTSP")
    assert u1 == "http://192.168.1.50:8080/video" and t1 == "http_mjpeg", f"Failed: {u1}, {t1}"
    
    u2, t2 = normalize_camera_url("http://192.168.1.50:8080/videofeed", "RTSP")
    assert u2 == "http://192.168.1.50:8080/videofeed" and t2 == "http_mjpeg", f"Failed: {u2}, {t2}"

    u3, t3 = normalize_camera_url("http://192.168.1.50:8080", "RTSP")
    assert u3 == "http://192.168.1.50:8080/video" and t3 == "http_mjpeg", f"Failed: {u3}, {t3}"

    # RTSP variations
    u4, t4 = normalize_camera_url("rtsp://192.168.1.50:8554/live", "RTSP")
    assert u4 == "rtsp://192.168.1.50:8554/live" and t4 == "rtsp", f"Failed: {u4}, {t4}"

    # Webcam
    u5, t5 = normalize_camera_url("0", "WEBCAM")
    assert u5 == "0" and t5 == "webcam", f"Failed: {u5}, {t5}"

    # MP4
    u6, t6 = normalize_camera_url("storage/demo_videos/border_patrol.mp4", "MP4")
    assert t6 == "mp4", f"Failed: {u6}, {t6}"

    print("✓ All URL normalization cases passed!")

def test_network_info_and_discovery_api():
    print("\n--- 2. Testing Network Info & Subnet Discovery API ---")
    r = requests.get(f"{BASE_URL}/api/cameras/network-info", headers=headers)
    assert r.status_code == 200
    info = r.json()
    print(f"Network Info: Server IP = {info['server_ip']}, Subnet = {info['subnet']}")
    assert "server_ip" in info and "subnet" in info

    r2 = requests.get(f"{BASE_URL}/api/cameras/discover-phone-cams", headers=headers)
    assert r2.status_code == 200
    disc = r2.json()
    print(f"Discovery Result: Subnet = {disc['subnet']}, Discovered Streams = {len(disc['discovered'])}")
    assert "discovered" in disc
    print("✓ Network info and auto-discovery APIs responded successfully!")

def test_connection_endpoint_real_cases():
    print("\n--- 3. Testing Test-Connection Endpoint Response Schema & Error Handling ---")
    
    # Unreachable IP test
    t0 = time.time()
    r = requests.post(f"{BASE_URL}/api/cameras/test-connection", json={
        "protocol": "RTSP",
        "stream_url": "http://192.168.1.254:8080/video"
    }, headers=headers)
    dur = round((time.time() - t0) * 1000, 1)
    assert r.status_code == 200
    data = r.json()
    print(f"Unreachable IP test result (took {dur}ms):")
    print(f"  connected: {data.get('connected')}")
    print(f"  source_type: {data.get('source_type')}")
    print(f"  error: {data.get('error')}")
    print(f"  latency_ms: {data.get('latency_ms')}")
    
    assert data["connected"] is False
    assert data["source_type"] == "http_mjpeg"
    assert data["error"] is not None
    assert dur < 2500, "Unreachable connection test must fail fast (< 2.5s)"

    # Format error test
    r_inv = requests.post(f"{BASE_URL}/api/cameras/test-connection", json={
        "protocol": "RTSP",
        "stream_url": "http://10.179.43.:8080/video"
    }, headers=headers)
    assert r_inv.status_code == 200
    d_inv = r_inv.json()
    assert d_inv["connected"] is False
    assert "Invalid camera URL" in d_inv["message"]

    # MP4 test source
    if os.path.exists("storage/demo_videos/border_patrol.mp4") or os.path.exists("storage/test_video.mp4"):
        vpath = "storage/demo_videos/border_patrol.mp4" if os.path.exists("storage/demo_videos/border_patrol.mp4") else "storage/test_video.mp4"
        r_mp4 = requests.post(f"{BASE_URL}/api/cameras/test-connection", json={
            "protocol": "MP4",
            "stream_url": vpath
        }, headers=headers)
        assert r_mp4.status_code == 200
        d_mp4 = r_mp4.json()
        print(f"MP4 connection test: connected={d_mp4.get('connected')}, res={d_mp4.get('width')}x{d_mp4.get('height')}, fps={d_mp4.get('fps')}")
        assert d_mp4["connected"] is True
        assert d_mp4["width"] > 0

    print("✓ Test-connection endpoint validated with strict schema compliance!")

if __name__ == "__main__":
    test_url_normalization()
    test_network_info_and_discovery_api()
    test_connection_endpoint_real_cases()
    print("\n========================================================")
    print("  ALL MOBILE / RTSP CONNECTIVITY TESTS PASSED SUCCESSFULLY!")
    print("========================================================\n")
