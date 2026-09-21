"""
End-to-End Watchlist Movement Tracking Integration Test
Verifies the exact 16-step user scenario:
1. Real watchlist person enrolled in database.
2. Camera 1 connects.
3. Person shown to Camera 1 -> Real face match confirmed.
4. Movement event #1 stored with real camera ID, location, timestamp, similarity, evidence.
5. Camera 2 connects simultaneously.
6. Same person shown to Camera 2 -> Real face match confirmed.
7. Movement event #2 stored -> Chain is Camera 1 -> Camera 2.
8. API query (GET /api/movement/chains) verifies real chain survives page refresh.
9. Camera 2 disconnects -> Previous movement history remains intact, no new events generated.
"""

import asyncio
import os
import time
import uuid
from datetime import datetime
import cv2
import numpy as np
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from database.connection import engine, SessionLocal
from database.schema import (
    Camera, FaceWatchlist, WatchlistMovementChain, WatchlistMovementEvent
)
from ai_engine.surveillance_agent import AISurveillanceAgent
from ai_engine.face.real_face_engine import RealFaceEngine
from backend.main import app
from backend.auth import create_access_token

class MockWS:
    def __init__(self):
        self.messages = []
    async def broadcast(self, msg):
        self.messages.append(msg)

async def _run_e2e_test():
    db = SessionLocal()
    ws_mock = MockWS()

    test_cam1_num = "E2E-CAM-01"
    test_cam2_num = "E2E-CAM-02"
    test_person_badge = "E2E-POI-999"

    # Clean up any leftover records for these test keys
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text("""
            DELETE FROM watchlist_movement_events 
            WHERE watchlist_person_id IN (SELECT id FROM face_watchlist WHERE person_id = :pid)
               OR camera_id IN (SELECT id FROM cameras WHERE camera_id IN (:c1, :c2))
        """), {"pid": test_person_badge, "c1": test_cam1_num, "c2": test_cam2_num})
        conn.execute(text("""
            DELETE FROM watchlist_movement_chains 
            WHERE watchlist_person_id IN (SELECT id FROM face_watchlist WHERE person_id = :pid)
        """), {"pid": test_person_badge})
        for tbl in ["face_detections", "evidence", "alerts", "incidents", "events", "camera_zones", "camera_health", "anpr_results"]:
            for cid in [test_cam1_num, test_cam2_num]:
                conn.execute(text(f"DELETE FROM {tbl} WHERE camera_id = :cid OR camera_id IN (SELECT id FROM cameras WHERE camera_id = :cid)"), {"cid": cid})
        conn.execute(text("DELETE FROM face_watchlist WHERE person_id = :pid"), {"pid": test_person_badge})
        for cid in [test_cam1_num, test_cam2_num]:
            conn.execute(text("DELETE FROM cameras WHERE camera_id = :cid"), {"cid": cid})
        conn.execute(text("PRAGMA foreign_keys = ON"))

    try:
        # 1. Setup Camera 1 and Camera 2
        cam1 = Camera(
            id=str(uuid.uuid4()),
            camera_id=test_cam1_num,
            name="Main Entrance Gate",
            location="Terminal Alpha Gate",
            latitude=26.9124,
            longitude=70.9025,
            protocol="MP4",
            stream_url="storage/demo_videos/border_patrol.mp4",
            status="ONLINE"
        )
        cam2 = Camera(
            id=str(uuid.uuid4()),
            camera_id=test_cam2_num,
            name="Perimeter Fence West",
            location="Sector 7 Border Fence",
            latitude=26.9200,
            longitude=70.9100,
            protocol="MP4",
            stream_url="storage/demo_videos/border_patrol.mp4",
            status="ONLINE"
        )
        db.add_all([cam1, cam2])
        db.commit()

        # 2. Enroll a Real Watchlist Person using actual face embedding from storage/test_person.jpg
        img_person = cv2.imread("storage/test_person.jpg")
        assert img_person is not None, "Real test image must exist"
        face_engine = RealFaceEngine()
        faces = face_engine.detect_faces(img_person)
        assert len(faces) > 0, "Face must be detected in real image"
        feat = face_engine.extract_embedding(img_person, faces[0].raw_face_array)
        assert feat is not None, "Neural feature embedding must be extracted"
        norm_feat = (feat / (np.linalg.norm(feat) + 1e-6)).flatten().tolist()

        real_person = FaceWatchlist(
            id=str(uuid.uuid4()),
            name="COMMANDER SANTHOSH",
            person_id=test_person_badge,
            category="WATCHLIST",
            photo_url="/api/faces/watchlist/photo/test_photo.jpg",
            embedding=norm_feat,
            is_active=True,
            notes="High-profile subject for E2E movement tracking"
        )
        db.add(real_person)
        db.commit()

        # 3. Connect Camera 1 and show person
        agent_cam1 = AISurveillanceAgent(camera_id=test_cam1_num, websocket_manager=ws_mock)
        for _ in range(4):
            await agent_cam1.process_frame(img_person, loop_start_time=time.time())
            await asyncio.sleep(0.25)

        # Verify movement event #1 stored in DB
        db.expire_all()
        chain = db.query(WatchlistMovementChain).filter(
            WatchlistMovementChain.watchlist_person_id == real_person.id
        ).first()
        assert chain is not None, "Movement chain must be created in DB for real person"
        assert chain.person_name == "COMMANDER SANTHOSH"
        assert chain.current_camera_number == test_cam1_num
        assert chain.current_location == "Terminal Alpha Gate"
        assert chain.status == "ACTIVE"

        events = db.query(WatchlistMovementEvent).filter(
            WatchlistMovementEvent.chain_id == chain.id
        ).order_by(WatchlistMovementEvent.sequence_number.asc()).all()
        assert len(events) == 1, "Exactly 1 movement event must be stored for Camera 1"
        assert events[0].camera_number == test_cam1_num
        assert events[0].sequence_number == 1
        assert events[0].location == "Terminal Alpha Gate"
        assert events[0].face_similarity > 0.40, "Real similarity must be positive"
        assert events[0].evidence_url is not None, "Real evidence snapshot URL must be present"

        # 4. Connect Camera 2 simultaneously and show the SAME person
        agent_cam2 = AISurveillanceAgent(camera_id=test_cam2_num, websocket_manager=ws_mock)
        for _ in range(4):
            await agent_cam2.process_frame(img_person, loop_start_time=time.time())
            await asyncio.sleep(0.25)

        # Verify movement event #2 stored in DB on the SAME chain
        db.expire_all()
        chain_after = db.query(WatchlistMovementChain).filter(
            WatchlistMovementChain.watchlist_person_id == real_person.id
        ).first()
        assert chain_after.id == chain.id, "Must be the SAME chain for the same person"
        assert chain_after.current_camera_number == test_cam2_num, "Current camera must update to Camera 2"
        assert chain_after.current_location == "Sector 7 Border Fence", "Location must update to Camera 2"

        events_after = db.query(WatchlistMovementEvent).filter(
            WatchlistMovementEvent.chain_id == chain.id
        ).order_by(WatchlistMovementEvent.sequence_number.asc()).all()
        assert len(events_after) == 2, f"Expected 2 movement events (Camera 1 -> Camera 2), got {len(events_after)}"
        assert events_after[0].sequence_number == 1 and events_after[0].camera_number == test_cam1_num
        assert events_after[1].sequence_number == 2 and events_after[1].camera_number == test_cam2_num
        assert events_after[1].location == "Sector 7 Border Fence"
        assert events_after[1].evidence_url is not None, "Camera 2 evidence URL must be present"

        # 5. Simulate Page Refresh: Call GET /api/movement/chains with auth
        client = TestClient(app)
        token = create_access_token({"sub": "admin"})
        res = client.get("/api/movement/chains", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        chains_json = res.json()
        target_chain = next(c for c in chains_json if c["watchlist_person_id"] == real_person.id)
        assert target_chain["person_name"] == "COMMANDER SANTHOSH"
        assert target_chain["events_count"] == 2
        assert target_chain["events"][0]["camera_number"] == test_cam1_num
        assert target_chain["events"][1]["camera_number"] == test_cam2_num

        # 6. Disconnect Camera 2
        agent_cam2.cleanup_live_session()
        cam2.status = "DISCONNECTED"
        db.commit()

        # Verify previous real movement history remains intact in DB
        db.expire_all()
        events_disconnected = db.query(WatchlistMovementEvent).filter(
            WatchlistMovementEvent.chain_id == chain.id
        ).order_by(WatchlistMovementEvent.sequence_number.asc()).all()
        assert len(events_disconnected) == 2, "Historical records must remain intact after disconnection"
        assert events_disconnected[0].camera_number == test_cam1_num
        assert events_disconnected[1].camera_number == test_cam2_num

    finally:
        # Clean up test entities
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            conn.execute(text("""
                DELETE FROM watchlist_movement_events 
                WHERE watchlist_person_id IN (SELECT id FROM face_watchlist WHERE person_id = :pid)
                   OR camera_id IN (SELECT id FROM cameras WHERE camera_id IN (:c1, :c2))
            """), {"pid": test_person_badge, "c1": test_cam1_num, "c2": test_cam2_num})
            conn.execute(text("""
                DELETE FROM watchlist_movement_chains 
                WHERE watchlist_person_id IN (SELECT id FROM face_watchlist WHERE person_id = :pid)
            """), {"pid": test_person_badge})
            for tbl in ["face_detections", "evidence", "alerts", "incidents", "events", "camera_zones", "camera_health", "anpr_results"]:
                for cid in [test_cam1_num, test_cam2_num]:
                    conn.execute(text(f"DELETE FROM {tbl} WHERE camera_id = :cid OR camera_id IN (SELECT id FROM cameras WHERE camera_id = :cid)"), {"cid": cid})
            conn.execute(text("DELETE FROM face_watchlist WHERE person_id = :pid"), {"pid": test_person_badge})
            for cid in [test_cam1_num, test_cam2_num]:
                conn.execute(text("DELETE FROM cameras WHERE camera_id = :cid"), {"cid": cid})
            conn.execute(text("PRAGMA foreign_keys = ON"))
        db.close()

def test_watchlist_movement_e2e_real_flow():
    asyncio.run(_run_e2e_test())
