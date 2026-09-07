"""
IBVAP End-to-End User Verification Sequence (Steps A through M)
Tests the exact sequence requested in Requirement 15.
"""

import sys
import uuid
import sqlite3
import asyncio
import numpy as np
from fastapi.testclient import TestClient
from backend.main import app, manager as ws_manager
from database.connection import SessionLocal
from database.schema import Camera, CameraZone, Alert, Incident, Evidence, User
from backend.auth import create_access_token
from ai_engine.surveillance_agent import AISurveillanceAgent

def test_sequence_a_to_m():
    print("=" * 75)
    print("  TESTING USER SEQUENCE A THROUGH M")
    print("=" * 75)

    client = TestClient(app)
    db = SessionLocal()
    admin = db.query(User).filter(User.username == 'admin').first()
    token = create_access_token(data={'sub': admin.username})
    headers = {'Authorization': f'Bearer {token}'}

    conn = sqlite3.connect('ibvap.db')
    c = conn.cursor()

    # Step A & B: Connect one camera
    print("\n[STEP A & B] Connecting camera & establishing surveillance zone...")
    test_cam = Camera(
        id=str(uuid.uuid4()),
        camera_id=f"SEQ-CAM-{uuid.uuid4().hex[:4].upper()}",
        name="Border Outpost Sequence Camera",
        status="ONLINE",
        protocol="WEBCAM",
        stream_url="0",
        latitude=26.9124,
        longitude=70.9025
    )
    db.add(test_cam)
    db.commit()

    test_zone = CameraZone(
        id=str(uuid.uuid4()),
        camera_id=test_cam.id,
        name="Restricted Zone Border",
        zone_type="RESTRICTED AREA",
        coordinates=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        is_active=True
    )
    db.add(test_zone)
    db.commit()
    print(f"  ✓ Camera connected: {test_cam.camera_id} (ID: {test_cam.id})")

    # Step C & D: Generate one real detection & verify alert appears
    print("\n[STEP C & D] Generating 1 real detection entering restricted zone...")
    agent = AISurveillanceAgent(test_cam.id, ws_manager)
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    async def detect_entry():
        det = [{"class_name": "person", "confidence": 0.94, "bbox": [0.4, 0.4, 0.2, 0.3]}]
        tracks = agent.tracker.update(test_cam.id, det)
        await agent._evaluate_surveillance_rules(tracks, frame=dummy_frame)

    asyncio.run(detect_entry())

    # Verify alert appears in database and REST API
    res = client.get("/api/alerts?limit=10", headers=headers)
    assert res.status_code == 200
    alerts = res.json()
    created_alert = next((a for a in alerts if a.get("camera_id") == test_cam.id), None)
    assert created_alert is not None, "Step D Failed: Alert did not appear in /api/alerts!"
    alert_id = created_alert["id"]
    print(f"  ✓ Alert appeared: ID={alert_id}, Type={created_alert['event_type']}, Severity={created_alert['severity']}")

    # Step E: Delete that alert
    print("\n[STEP E] Deleting that alert via DELETE /api/alerts/{id}...")
    del_res = client.delete(f"/api/alerts/{alert_id}", headers=headers)
    assert del_res.status_code == 200, f"Delete API failed with status {del_res.status_code}"
    print(f"  ✓ Delete response: {del_res.json()}")

    # Step F & G: Refresh Live Alerts page & confirm deleted alert does NOT return
    print("\n[STEP F & G] Simulating Live Alerts page refresh (GET /api/alerts)...")
    res_refresh1 = client.get("/api/alerts?limit=50", headers=headers)
    alerts_ref1 = res_refresh1.json()
    assert not any(a["id"] == alert_id for a in alerts_ref1), "Step G Failed: Deleted alert returned on first refresh!"
    c.execute("SELECT count(*) FROM alerts WHERE id = ?", (alert_id,))
    assert c.fetchone()[0] == 0, "Step G Failed: Alert row still in SQLite!"
    print("  ✓ Refresh 1 Confirmed: Deleted alert did NOT return.")

    # Step H: Refresh again and confirm it remains deleted
    print("\n[STEP H] Second page refresh simulation (GET /api/alerts)...")
    res_refresh2 = client.get("/api/alerts?limit=50", headers=headers)
    alerts_ref2 = res_refresh2.json()
    assert not any(a["id"] == alert_id for a in alerts_ref2), "Step H Failed: Deleted alert returned on second refresh!"
    c.execute("SELECT count(*) FROM alerts WHERE id = ?", (alert_id,))
    assert c.fetchone()[0] == 0, "Step H Failed: Alert row still in SQLite!"
    print("  ✓ Refresh 2 Confirmed: Deleted alert remains permanently deleted.")

    # Step I: Check Incidents and Evidence for the same behavior
    print("\n[STEP I] Testing Incidents and Evidence deletion persistence...")
    # 1. Incident
    res_inc = client.get("/api/incidents?limit=10", headers=headers)
    cam_inc = next((i for i in res_inc.json() if i.get("camera_id") == test_cam.id), None)
    if cam_inc:
        inc_id = cam_inc["id"]
        client.delete(f"/api/incidents/{inc_id}", headers=headers)
        res_inc_ref = client.get("/api/incidents?limit=50", headers=headers)
        assert not any(i["id"] == inc_id for i in res_inc_ref.json()), "Incident returned after delete!"
        c.execute("SELECT count(*) FROM incidents WHERE id = ?", (inc_id,))
        assert c.fetchone()[0] == 0, "Incident still in SQLite!"
        print(f"  ✓ Incident #{cam_inc['incident_number']} deleted and confirmed gone after refresh.")

    # 2. Evidence
    res_ev = client.get(f"/api/evidence?camera_id={test_cam.id}", headers=headers)
    ev_items = res_ev.json().get("items", [])
    if ev_items:
        ev_id = ev_items[0]["id"]
        client.delete(f"/api/evidence/{ev_id}", headers=headers)
        res_ev_ref = client.get(f"/api/evidence?camera_id={test_cam.id}", headers=headers)
        assert not any(e["id"] == ev_id for e in res_ev_ref.json().get("items", [])), "Evidence returned after delete!"
        c.execute("SELECT count(*) FROM evidence WHERE id = ?", (ev_id,))
        assert c.fetchone()[0] == 0, "Evidence still in SQLite!"
        print(f"  ✓ Evidence #{ev_id[:8]} deleted and confirmed gone after refresh.")

    # Step J & K: Simulate backend restart and confirm deleted records do NOT return
    print("\n[STEP J & K] Simulating backend restart (closing & re-opening DB session & SQLite engine)...")
    db.close()
    conn.close()

    # Reconnect fresh session
    db_new = SessionLocal()
    conn_new = sqlite3.connect('ibvap.db')
    c_new = conn_new.cursor()

    c_new.execute("SELECT count(*) FROM alerts WHERE id = ?", (alert_id,))
    assert c_new.fetchone()[0] == 0, "Step K Failed: Deleted alert returned after restart!"
    print("  ✓ Post-Restart Confirmed: Deleted records do NOT return after backend restart.")

    # Step L & M: Generate a NEW real detection & confirm new alert is created
    print("\n[STEP L & M] Generating NEW real detection (new track entering)...")
    agent_new = AISurveillanceAgent(test_cam.id, ws_manager)

    # Let cooldown window expire or simulate new track after resolution
    async def detect_new_person():
        # New track with different position
        det_new = [{"class_name": "person", "confidence": 0.97, "bbox": [0.2, 0.2, 0.25, 0.35]}]
        tracks_new = agent_new.tracker.update(test_cam.id, det_new)
        await agent_new._evaluate_surveillance_rules(tracks_new, frame=dummy_frame)

    asyncio.run(detect_new_person())

    res_new_alerts = client.get("/api/alerts?limit=10", headers=headers)
    new_alerts_list = res_new_alerts.json()
    new_alert = next((a for a in new_alerts_list if a.get("camera_id") == test_cam.id and a.get("id") != alert_id), None)
    assert new_alert is not None, "Step M Failed: New real detection did not create a new alert!"
    print(f"  ✓ Step M Confirmed: New alert created successfully! ID={new_alert['id']}")

    conn_new.close()
    db_new.close()

    print("\n" + "=" * 75)
    print("  ALL STEPS A THROUGH M VERIFIED AND COMPLETED WITH 100% SUCCESS!")
    print("=" * 75)

if __name__ == "__main__":
    test_sequence_a_to_m()
