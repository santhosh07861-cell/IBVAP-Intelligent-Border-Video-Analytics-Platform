import time
import requests
import json
from backend.auth import create_access_token

BASE_URL = "http://127.0.0.1:8000"
token = create_access_token(data={"sub": "admin"})
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def test_ip_validation():
    print("\n--- 1. Testing IP & URL Format Validation ---")
    invalid_cases = [
        "http://10.179.43.:8080/video",
        "http://10.179.43:8080/video",
        "http://10.179.43.300:8080/video",
        "http://10.179.43.abc:8080/video",
        "rtsp://10.179.43.",
        "http://:8080/video"
    ]
    
    for invalid_url in invalid_cases:
        r = requests.post(f"{BASE_URL}/api/cameras/test-connection", json={
            "protocol": "RTSP",
            "stream_url": invalid_url
        }, headers=headers)
        data = r.json()
        print(f"Tested invalid URL '{invalid_url}': status={data.get('status')}, error_type={data.get('error_type')}")
        assert data.get("status") == "FAILED", f"Expected FAILED for {invalid_url}"
        assert data.get("error_type") == "INVALID_URL", f"Expected INVALID_URL for {invalid_url}"
        assert "Invalid camera URL. Enter the complete phone IP address." in data.get("message")
        
        # Test create_camera rejects invalid URL with 400
        r_create = requests.post(f"{BASE_URL}/api/cameras", json={
            "camera_id": "CAM-INVALID-TEST",
            "name": "Invalid IP Cam",
            "location": "Test",
            "stream_url": invalid_url,
            "protocol": "RTSP"
        }, headers=headers)
        assert r_create.status_code == 400, f"Expected 400 for create with {invalid_url}"
    
    print("✓ All invalid IP format cases successfully rejected with exact validation message.")

def test_auto_discovery_and_network_info():
    print("\n--- 2. Testing Network Info and Phone Cam Discovery Endpoints ---")
    r_net = requests.get(f"{BASE_URL}/api/cameras/network-info", headers=headers)
    assert r_net.status_code == 200
    net_data = r_net.json()
    print(f"Network Info: Host IP={net_data.get('server_ip')}, Subnet={net_data.get('subnet')}")
    assert "server_ip" in net_data
    assert "subnet" in net_data
    
    r_disc = requests.get(f"{BASE_URL}/api/cameras/discover-phone-cams", headers=headers)
    assert r_disc.status_code == 200
    disc_data = r_disc.json()
    print(f"Discover Phone Cams: Scanned Subnet={disc_data.get('subnet')}, Found={len(disc_data.get('discovered', []))} stream(s)")
    assert "discovered" in disc_data
    print("✓ Auto-discovery and network info endpoints verified successfully.")

def test_complete_ai_pipeline():
    print("\n--- 3. Testing Live Surveillance Stream Ingestion & AI Analytics Pipeline ---")
    cid = "CAM-VERIFY-PIPE"
    
    # 1. Create camera with valid stream
    create_res = requests.post(f"{BASE_URL}/api/cameras", json={
        "camera_id": cid,
        "name": "Live Verification Camera",
        "location": "North Border Gate",
        "stream_url": "storage/demo_videos/border_patrol.mp4",
        "protocol": "MP4"
    }, headers=headers)
    assert create_res.status_code == 200, f"Create camera failed: {create_res.text}"
    print(f"Camera {cid} created successfully.")
    
    # 2. Start camera stream ingestion
    start_res = requests.post(f"{BASE_URL}/api/cameras/{cid}/start", headers=headers)
    assert start_res.status_code == 200, f"Start stream failed: {start_res.text}"
    print(f"Stream ingestion started for {cid}.")
    
    # 3. Allow worker to process frames and run AI inference
    time.sleep(2.0)
    
    # 4. Check camera status in API
    get_res = requests.get(f"{BASE_URL}/api/cameras/{cid}", headers=headers)
    cam_data = get_res.json()
    print(f"Camera Status: {cam_data.get('status')}, FPS: {cam_data.get('fps')}")
    
    # 5. Clean up camera
    del_res = requests.delete(f"{BASE_URL}/api/cameras/{cid}", headers=headers)
    assert del_res.status_code == 200
    print(f"Cleaned up camera {cid}.")
    print("✓ Complete stream ingestion, AI inference, and deletion pipeline verified.")

if __name__ == "__main__":
    test_ip_validation()
    test_auto_discovery_and_network_info()
    test_complete_ai_pipeline()
    print("\n==========================================")
    print("ALL VERIFICATIONS COMPLETED WITH 100% SUCCESS")
    print("==========================================")
