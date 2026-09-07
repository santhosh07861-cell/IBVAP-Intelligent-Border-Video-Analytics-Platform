import sqlite3
import requests
import json
from pathlib import Path
from backend.auth import create_access_token

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = str(Path(__file__).parent / "ibvap.db")

def get_auth_token():
    return create_access_token(data={"sub": "admin"})


def check_db(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    res = c.fetchall()
    conn.close()
    return res

def test_all():
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    print("✓ Successfully authenticated with JWT")

    # 1. Check current evidence count
    initial_ev_count = check_db("SELECT count(*) FROM evidence")[0][0]
    print(f"Initial evidence rows in DB: {initial_ev_count}")

    # 2. Test Clear All Evidence
    print("\n--- Testing POST /api/evidence/clear-all ---")
    resp = requests.post(f"{BASE_URL}/api/evidence/clear-all", json={}, headers=headers)
    print(f"Response ({resp.status_code}): {resp.json()}")
    assert resp.status_code == 200
    ev_count_after = check_db("SELECT count(*) FROM evidence")[0][0]
    print(f"Evidence count after clear-all: {ev_count_after}")
    assert ev_count_after == 0

    # 3. Test GET /api/evidence returns 0
    resp = requests.get(f"{BASE_URL}/api/evidence", headers=headers)
    assert resp.status_code == 200
    ev_data = resp.json()
    print(f"GET /api/evidence total: {ev_data.get('total')}, items len: {len(ev_data.get('items', []))}")
    assert ev_data.get("total") == 0
    assert len(ev_data.get("items", [])) == 0

    # 4. Test Clear All Alerts
    print("\n--- Testing POST /api/alerts/clear-all ---")
    resp = requests.post(f"{BASE_URL}/api/alerts/clear-all", json={}, headers=headers)
    print(f"Response ({resp.status_code}): {resp.json()}")
    assert resp.status_code == 200
    alert_count_after = check_db("SELECT count(*) FROM alerts")[0][0]
    print(f"Alerts count after clear-all: {alert_count_after}")
    assert alert_count_after == 0

    # 5. Test GET /api/alerts returns []
    resp = requests.get(f"{BASE_URL}/api/alerts", headers=headers)
    assert resp.status_code == 200
    alerts_data = resp.json()
    print(f"GET /api/alerts len: {len(alerts_data)}")
    assert len(alerts_data) == 0

    # 6. Test Clear All Incidents
    print("\n--- Testing POST /api/incidents/clear-all ---")
    resp = requests.post(f"{BASE_URL}/api/incidents/clear-all", json={}, headers=headers)
    print(f"Response ({resp.status_code}): {resp.json()}")
    assert resp.status_code == 200
    inc_count_after = check_db("SELECT count(*) FROM incidents")[0][0]
    print(f"Incidents count after clear-all: {inc_count_after}")
    assert inc_count_after == 0

    # 7. Test Clear All Face Detections
    print("\n--- Testing POST /api/faces/detections/clear-all ---")
    resp = requests.post(f"{BASE_URL}/api/faces/detections/clear-all", json={}, headers=headers)
    print(f"Response ({resp.status_code}): {resp.json()}")
    assert resp.status_code == 200
    faces_count_after = check_db("SELECT count(*) FROM face_detections")[0][0]
    print(f"Face detections count after clear-all: {faces_count_after}")
    assert faces_count_after == 0

    # 8. Test Lifecycle: Insert 1 test evidence row, delete it, verify it is gone and doesn't restore on refresh
    print("\n--- Testing Single Record Delete & Non-Reappearance Lifecycle ---")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    test_id = "test-single-ev-999"
    c.execute("""
        INSERT INTO evidence (id, camera_id, evidence_type, file_path, file_url, metadata_json, created_at)
        VALUES (?, ?, 'DETECTION', '', '/api/placeholder.jpg', '{"object_class":"person","track_id":"P-999","confidence":0.95}', datetime('now'))
    """, (test_id, "CAM-01"))
    conn.commit()
    conn.close()

    # Verify present in DB & API
    assert check_db("SELECT count(*) FROM evidence WHERE id = ?", (test_id,))[0][0] == 1
    resp = requests.get(f"{BASE_URL}/api/evidence", headers=headers)
    assert resp.json()["total"] == 1
    print(f"✓ Inserted 1 test record: {test_id}, API shows total=1")

    # Now DELETE via API (simulating user clicking bin button)
    del_resp = requests.delete(f"{BASE_URL}/api/evidence/{test_id}", headers=headers)
    assert del_resp.status_code == 200
    print(f"✓ DELETE response: {del_resp.json()}")

    # Verify directly in SQLite
    db_after_del = check_db("SELECT count(*) FROM evidence WHERE id = ?", (test_id,))[0][0]
    print(f"Direct SQLite count for {test_id} immediately after delete: {db_after_del}")
    assert db_after_del == 0

    # Simulate page refresh by fetching GET /api/evidence
    refresh_resp = requests.get(f"{BASE_URL}/api/evidence", headers=headers)
    refresh_data = refresh_resp.json()
    print(f"Simulated page refresh GET /api/evidence: total={refresh_data.get('total')}, items={refresh_data.get('items')}")
    assert refresh_data.get("total") == 0
    assert len(refresh_data.get("items", [])) == 0
    print("✓ Confirmed: Deleted data does NOT reappear after page refresh!")

    print("\n==========================================")
    print("🎉 ALL LIFECYCLE & PURGE TESTS PASSED (100%)")
    print("==========================================")

if __name__ == "__main__":
    test_all()
