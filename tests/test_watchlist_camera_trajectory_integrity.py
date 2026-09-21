"""
Test Suite: Watchlist Movement Tracking Camera Trajectory Integrity
Verifies:
1. Camera identity is ALWAYS the actual camera identifier from the database, NEVER array index or sequence number.
2. Consecutive detections on the SAME camera are consolidated into ONE camera visit node with first_seen_at and last_seen_at.
3. Cross-camera transition creates a new node for the new camera: e.g. CAM-01 -> CAM-02.
4. Consecutive frames on the same camera do NOT generate duplicate sequence nodes (e.g. not 1 CAM-6444, 2 CAM-6444, 3 CAM-6444).
5. Chronological event index is explicitly distinct from camera identity (EVENT 1, EVENT 2).
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta
import cv2
import numpy as np
import pytest
from sqlalchemy import text

from database.connection import engine, SessionLocal
from database.schema import Camera, FaceWatchlist, WatchlistMovementChain, WatchlistMovementEvent
from ai_engine.surveillance_agent import AISurveillanceAgent
from ai_engine.face.real_face_engine import RealFaceEngine
from backend.routers.movement_router import _serialize_chain

class MockWS:
    def __init__(self):
        self.messages = []
    async def broadcast(self, msg):
        self.messages.append(msg)

async def _run_test():
    db = SessionLocal()
    ws_mock = MockWS()

    cam_id_1 = "CAM-TRAJ-01"
    cam_id_2 = "CAM-TRAJ-02"
    poi_id = "POI-TRAJ-TEST"

    # Clean up test records
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text("DELETE FROM watchlist_movement_events WHERE camera_number IN (:c1, :c2) OR watchlist_person_id IN (SELECT id FROM face_watchlist WHERE person_id = :p)"), {"c1": cam_id_1, "c2": cam_id_2, "p": poi_id})
        conn.execute(text("DELETE FROM watchlist_movement_chains WHERE watchlist_person_id IN (SELECT id FROM face_watchlist WHERE person_id = :p)"), {"p": poi_id})
        conn.execute(text("DELETE FROM cameras WHERE camera_id IN (:c1, :c2)"), {"c1": cam_id_1, "c2": cam_id_2})
        conn.execute(text("DELETE FROM face_watchlist WHERE person_id = :p"), {"p": poi_id})
        conn.execute(text("PRAGMA foreign_keys = ON"))

    try:
        # 1. Create real test cameras
        c1 = Camera(
            id=str(uuid.uuid4()),
            camera_id=cam_id_1,
            name="North Gate Terminal",
            location="Sector Alpha Checkpoint",
            latitude=26.9124,
            longitude=70.9025,
            protocol="MP4",
            stream_url="storage/demo_videos/border_patrol.mp4",
            status="ONLINE"
        )
        c2 = Camera(
            id=str(uuid.uuid4()),
            camera_id=cam_id_2,
            name="Perimeter West Watchtower",
            location="Sector Beta Fence",
            latitude=26.9200,
            longitude=70.9100,
            protocol="MP4",
            stream_url="storage/demo_videos/border_patrol.mp4",
            status="ONLINE"
        )
        db.add_all([c1, c2])
        db.commit()

        # 2. Enroll real watchlist person
        img_person = cv2.imread("storage/test_person.jpg")
        assert img_person is not None, "storage/test_person.jpg must exist"
        face_engine = RealFaceEngine()
        faces = face_engine.detect_faces(img_person)
        assert len(faces) > 0, "Face must be detected"
        feat = face_engine.extract_embedding(img_person, faces[0].raw_face_array)
        norm_feat = (feat / (np.linalg.norm(feat) + 1e-6)).flatten().tolist()

        wl_person = FaceWatchlist(
            id=str(uuid.uuid4()),
            name="TRAJECTORY TEST SUBJECT",
            person_id=poi_id,
            category="WATCHLIST",
            photo_url="/api/faces/watchlist/photo/test.jpg",
            embedding=norm_feat,
            is_active=True
        )
        db.add(wl_person)
        db.commit()

        # 3. Process 5 frames on Camera 1 (CAM-TRAJ-01) over simulated elapsed time
        agent_c1 = AISurveillanceAgent(camera_id=cam_id_1, websocket_manager=ws_mock)
        for i in range(5):
            await agent_c1.process_frame(img_person, loop_start_time=time.time())
            await asyncio.sleep(0.1)

        db.expire_all()
        chain = db.query(WatchlistMovementChain).filter(
            WatchlistMovementChain.watchlist_person_id == wl_person.id
        ).first()
        assert chain is not None, "Movement chain must exist"

        events_c1 = db.query(WatchlistMovementEvent).filter(
            WatchlistMovementEvent.chain_id == chain.id
        ).all()

        # REQUIREMENT: Continuous observations on the SAME camera MUST be consolidated into exactly ONE visit node
        assert len(events_c1) == 1, f"Expected exactly 1 consolidated node for CAM-TRAJ-01, got {len(events_c1)}"
        assert events_c1[0].camera_number == cam_id_1, f"Camera must be {cam_id_1}, not an index"
        assert events_c1[0].camera_name == "North Gate Terminal"
        assert events_c1[0].location == "Sector Alpha Checkpoint"
        assert events_c1[0].first_seen_at is not None and events_c1[0].last_seen_at is not None
        assert events_c1[0].last_seen_at >= events_c1[0].first_seen_at

        # 4. Process frames on Camera 2 (CAM-TRAJ-02) -> Cross-camera transition
        agent_c2 = AISurveillanceAgent(camera_id=cam_id_2, websocket_manager=ws_mock)
        for i in range(5):
            await agent_c2.process_frame(img_person, loop_start_time=time.time())
            await asyncio.sleep(0.2)

        db.expire_all()
        events_cross = db.query(WatchlistMovementEvent).filter(
            WatchlistMovementEvent.chain_id == chain.id
        ).order_by(WatchlistMovementEvent.sequence_number.asc()).all()

        # REQUIREMENT: Trajectory now contains exactly 2 nodes: CAM-TRAJ-01 -> CAM-TRAJ-02
        assert len(events_cross) == 2, f"Expected exactly 2 nodes across 2 cameras, got {len(events_cross)}"
        assert events_cross[0].camera_number == cam_id_1, "Node 1 must be CAM-TRAJ-01"
        assert events_cross[1].camera_number == cam_id_2, "Node 2 must be CAM-TRAJ-02"
        assert events_cross[0].sequence_number == 1
        assert events_cross[1].sequence_number == 2

        # 5. Verify API serialization format
        api_data = _serialize_chain(chain, db)
        assert len(api_data["events"]) == 2
        assert api_data["events"][0]["camera_number"] == cam_id_1
        assert api_data["events"][1]["camera_number"] == cam_id_2
        assert api_data["events"][0]["event_label"] == "EVENT 1"
        assert api_data["events"][1]["event_label"] == "EVENT 2"
        assert api_data["events"][0]["camera_name"] == "North Gate Terminal"
        assert api_data["events"][1]["camera_name"] == "Perimeter West Watchtower"

        print("\n✓ SUCCESS: Camera identity is authoritative and same-camera detections are consolidated!")

    finally:
        # Cleanup
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            conn.execute(text("DELETE FROM watchlist_movement_events WHERE camera_number IN (:c1, :c2) OR watchlist_person_id IN (SELECT id FROM face_watchlist WHERE person_id = :p)"), {"c1": cam_id_1, "c2": cam_id_2, "p": poi_id})
            conn.execute(text("DELETE FROM watchlist_movement_chains WHERE watchlist_person_id IN (SELECT id FROM face_watchlist WHERE person_id = :p)"), {"p": poi_id})
            conn.execute(text("DELETE FROM cameras WHERE camera_id IN (:c1, :c2)"), {"c1": cam_id_1, "c2": cam_id_2})
            conn.execute(text("DELETE FROM face_watchlist WHERE person_id = :p"), {"p": poi_id})
            conn.execute(text("PRAGMA foreign_keys = ON"))
        db.close()

def test_same_camera_consolidation_and_real_camera_identity():
    asyncio.run(_run_test())
