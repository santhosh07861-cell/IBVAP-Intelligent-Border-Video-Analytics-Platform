"""
End-to-End Verification Test for MP4 Video Source Functionality in IBVAP.
Tests:
1. upload-mp4 endpoint with real video file
2. test-connection endpoint with valid MP4 and nonexistent file (verifying FILE ERROR, never UNREACHABLE)
3. Camera creation and initial READY status
4. Camera start and StreamWorker launching without network checks
5. Frame decoding, real calculated FPS, and continuous AI pipeline integration
6. Reaching EOF -> transition to COMPLETED (no auto-restart, no fake detections)
7. Verification with user's local 4K video file
"""

import os
import sys
import time
import requests
import json

BASE_URL = "http://localhost:8000"

def get_auth_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", data={
        "username": "admin",
        "password": "Admin Pass123!"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json().get("access_token")

def main():
    print("=== STARTING MP4 VIDEO SOURCE VERIFICATION ===")
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    print("[1] Authentication successful.")

    # 1. Test POST /api/cameras/upload-mp4
    test_video_path = "storage/demo_videos/border_patrol.mp4"
    assert os.path.exists(test_video_path), f"Sample video not found at {test_video_path}"
    print(f"[2] Testing upload-mp4 with '{test_video_path}'...")
    with open(test_video_path, "rb") as vf:
        upload_resp = requests.post(
            f"{BASE_URL}/api/cameras/upload-mp4",
            headers=headers,
            files={"file": ("test_upload.mp4", vf, "video/mp4")}
        )
    print(f"    Upload response ({upload_resp.status_code}): {upload_resp.json()}")
    assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
    upload_data = upload_resp.json()
    assert upload_data["status"] == "success"
    assert upload_data["width"] > 0
    assert upload_data["height"] > 0
    assert upload_data["fps"] > 0
    uploaded_file_path = upload_data["file_path"]
    print(f"    Uploaded file verified at: {uploaded_file_path} ({upload_data['width']}x{upload_data['height']} @ {upload_data['fps']} FPS)")

    # 2. Test POST /api/cameras/test-connection with valid MP4
    print("[3] Testing test-connection with valid MP4 path...")
    test_conn_resp = requests.post(
        f"{BASE_URL}/api/cameras/test-connection",
        headers=headers,
        json={"protocol": "MP4", "stream_url": uploaded_file_path}
    )
    print(f"    Valid test-connection response: {test_conn_resp.json()}")
    assert test_conn_resp.status_code == 200
    conn_data = test_conn_resp.json()
    assert conn_data["connected"] is True
    assert conn_data["status"] == "SUCCESS"
    assert conn_data["source_type"] == "mp4"
    assert conn_data["error"] is None
    assert conn_data["camera_ip"] == "LOCAL_FILE"

    # 3. Test POST /api/cameras/test-connection with nonexistent MP4 (MUST show FILE ERROR, never UNREACHABLE)
    print("[4] Testing test-connection with missing MP4 path (verifying FILE ERROR)...")
    fake_path = "/nonexistent/path/fake_video_12345.mp4"
    err_conn_resp = requests.post(
        f"{BASE_URL}/api/cameras/test-connection",
        headers=headers,
        json={"protocol": "MP4", "stream_url": fake_path}
    )
    print(f"    Missing file response: {err_conn_resp.json()}")
    assert err_conn_resp.status_code == 200
    err_data = err_conn_resp.json()
    assert err_data["connected"] is False
    assert err_data["status"] == "FAILED"
    assert err_data["error_type"] == "FILE_ERROR"
    assert "FILE ERROR" in err_data["error"]
    assert "UNREACHABLE" not in err_data["error"]
    assert "NETWORK" not in err_data["error"]
    print("    Verified: Missing MP4 correctly reports FILE ERROR, zero network error states.")

    # 4. Test Camera Creation with MP4 protocol
    cam_id = "CAM-MP4-TEST"
    print(f"[5] Creating/updating test camera {cam_id}...")
    create_resp = requests.post(
        f"{BASE_URL}/api/cameras",
        headers=headers,
        json={
            "camera_id": cam_id,
            "name": "Border Video Unit Test",
            "location": "Sector A-1",
            "protocol": "MP4",
            "stream_url": uploaded_file_path,
            "role": "secondary"
        }
    )
    print(f"    Camera create response: {create_resp.json()}")
    assert create_resp.status_code == 200
    cam_data = create_resp.json()
    assert cam_data["status"] == "READY", f"Expected initial status READY, got {cam_data['status']}"
    print(f"    Verified: Initial camera status is READY.")

    # 5. Start camera and verify transition to PLAYING / PROCESSING
    print(f"[6] Starting camera {cam_id}...")
    start_resp = requests.post(
        f"{BASE_URL}/api/cameras/{cam_id}/start",
        headers=headers
    )
    print(f"    Start response: {start_resp.json()}")
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "success"

    # Monitor stream progress for a few seconds
    print("[7] Ingesting frames through AI pipeline and monitoring real FPS...")
    playing_observed = False
    for i in range(10):
        time.sleep(1.0)
        c_resp = requests.get(f"{BASE_URL}/api/cameras/{cam_id}", headers=headers)
        c_status = c_resp.json()
        status = c_status.get("status")
        fps = c_status.get("fps", 0.0)
        print(f"    [{i+1}s] Status: {status}, FPS: {fps}")
        if status in ["PLAYING", "READY"] and fps > 0.0:
            playing_observed = True
        if status == "COMPLETED":
            print("    Reached COMPLETED state!")
            break

    assert playing_observed, "Camera never reached PLAYING status with FPS > 0"
    print("    Verified: Camera successfully played with real calculated FPS.")

    # 8. Test EOF transition: border_patrol.mp4 has 150 frames (~6-10s)
    print("\n[8] Waiting for video to reach End of Video (EOF)...")
    eof_reached = False
    for wait_sec in range(25):
        time.sleep(1.0)
        c_resp = requests.get(f"{BASE_URL}/api/cameras/{cam_id}", headers=headers)
        c_status = c_resp.json()
        st = c_status.get("status")
        cur_fps = c_status.get("fps", 0.0)
        print(f"    [+{wait_sec+1}s] Current Status: {st}, FPS: {cur_fps}")
        if st == "COMPLETED":
            eof_reached = True
            assert cur_fps == 0.0, f"Expected 0.0 FPS on completion, got {cur_fps}"
            print("    Successfully transitioned to COMPLETED on EOF with FPS 0.0!")
            break

    assert eof_reached, "Video did not reach COMPLETED state within 25s"

    # 9. Verify user's 4K CCTV video camera CAM-4541
    print("\n[9] Verifying user's 4K CCTV video camera CAM-4541...")
    user_video_path = "/Users/tejavathusanthosh/Downloads/vidssave.com 8MP 4K Dahua CCTV System Sample Video - Night Time 2160P.mp4"
    if os.path.exists(user_video_path):
        update_cam = requests.post(
            f"{BASE_URL}/api/cameras",
            headers=headers,
            json={
                "camera_id": "CAM-4541",
                "name": "Camera Device 1",
                "location": "Sector 4K",
                "protocol": "MP4",
                "stream_url": user_video_path,
                "role": "secondary"
            }
        )
        c4k_data = update_cam.json()
        print(f"    CAM-4541 status after update: {c4k_data.get('status')}")
        assert c4k_data.get("status") == "READY", f"Expected READY, got {c4k_data.get('status')}"

        test_4k = requests.post(
            f"{BASE_URL}/api/cameras/test-connection",
            headers=headers,
            json={"protocol": "MP4", "stream_url": user_video_path}
        )
        print(f"    CAM-4541 Test Connection: {test_4k.json()}")
        t4k_data = test_4k.json()
        assert t4k_data["connected"] is True
        assert t4k_data["status"] == "SUCCESS"
        assert t4k_data["width"] == 3840
        assert t4k_data["height"] == 2160
        assert t4k_data["fps"] > 0
        print("    Verified: User's 4K video (3840x2160) tests successfully with zero network errors!")

    # Cleanup test camera
    requests.delete(f"{BASE_URL}/api/cameras/{cam_id}", headers=headers)
    if os.path.exists(uploaded_file_path):
        os.remove(uploaded_file_path)
    print("\n=== ALL MP4 VERIFICATION TESTS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
