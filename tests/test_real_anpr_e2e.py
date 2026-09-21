"""
End-to-End Real ANPR Test: Surveillance Agent, Tracking, DB, and Multi-Camera
=============================================================================
Verifies:
1. SurveillanceAgent processes real vehicle detections through full ANPR pipeline.
2. Real vehicle with plate achieves CONFIRMED status with actual OCR confidence.
3. Real vehicle without plate achieves UNCERTAIN status with plate_number = NULL in DB.
4. Deduplication prevents multiple records for the same tracked vehicle.
5. Multiple cameras (CAM-01 and CAM-02) process simultaneously with strict independence.
"""

import os
import uuid
import pytest
import cv2
import numpy as np
from datetime import datetime

from database.connection import SessionLocal
from database.schema import ANPRResult, Camera
from ai_engine.surveillance_agent import AISurveillanceAgent
from ai_engine.tracking.tracker import TrackedObject
from backend.config import ANPR_OCR_CONFIDENCE_THRESHOLD


@pytest.fixture(scope="module")
def db_session():
    db = SessionLocal()
    yield db
    db.close()


@pytest.mark.anyio
async def test_anpr_e2e_vehicle_detection_and_null_handling(db_session):
    """
    Tests full AISurveillanceAgent._process_anpr_intelligence pipeline:
    - Vehicle with plate -> stored in DB with real recognized plate and OCR conf
    - Vehicle without plate -> stored in DB with plate_number = NULL, ocr_conf = 0.0
    - Multi-frame deduplication prevents duplicate DB records
    """
    # Create test cameras in database
    cam1_id_num = f"CAM-T1-{uuid.uuid4().hex[:4].upper()}"
    cam2_id_num = f"CAM-T2-{uuid.uuid4().hex[:4].upper()}"

    cam1 = Camera(
        id=f"test-cam1-{uuid.uuid4().hex[:6]}",
        camera_id=cam1_id_num,
        name="Sector Checkpoint 1",
        location="North Gate Checkpoint",
        stream_url="0",
        status="ACTIVE",
    )
    cam2 = Camera(
        id=f"test-cam2-{uuid.uuid4().hex[:6]}",
        camera_id=cam2_id_num,
        name="Sector Checkpoint 2",
        location="South Gate Checkpoint",
        stream_url="0",
        status="ACTIVE",
    )
    db_session.add(cam1)
    db_session.add(cam2)
    db_session.commit()

    from unittest.mock import AsyncMock, MagicMock
    ws_mock = MagicMock()
    ws_mock.broadcast = AsyncMock()

    agent1 = AISurveillanceAgent(camera_id=cam1.camera_id, websocket_manager=ws_mock)
    agent2 = AISurveillanceAgent(camera_id=cam2.camera_id, websocket_manager=ws_mock)

    try:
        # Create full camera frame (720x1280)
        frame = np.full((720, 1280, 3), 40, dtype=np.uint8)

        # Vehicle 1: Car with clear Indian license plate KA05MH2020 at [200:550, 100:600]
        v1_y1, v1_y2, v1_x1, v1_x2 = 200, 550, 100, 600
        frame[v1_y1:v1_y2, v1_x1:v1_x2] = 60
        # Draw plate in lower half of vehicle 1
        p_y1, p_y2, p_x1, p_x2 = 450, 520, 250, 480
        frame[p_y1:p_y2, p_x1:p_x2] = 250
        cv2.putText(frame, "KA05MH2020", (p_x1 + 10, p_y2 - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 0, 0), 2)

        # Vehicle 2: Bus with NO license plate at [200:550, 700:1200]
        v2_y1, v2_y2, v2_x1, v2_x2 = 200, 550, 700, 1200
        frame[v2_y1:v2_y2, v2_x1:v2_x2] = 80
        # Add bus windows (no text)
        frame[240:320, 720:1180] = 160

        fh, fw = frame.shape[:2]
        obj1 = TrackedObject(
            track_id=101,
            camera_id=cam1.camera_id,
            class_id=2,
            class_name="car",
            confidence=0.92,
            bbox=[v1_x1 / fw, v1_y1 / fh, (v1_x2 - v1_x1) / fw, (v1_y2 - v1_y1) / fh],
            center=((v1_x1 + v1_x2) / (2 * fw), (v1_y1 + v1_y2) / (2 * fh)),
            entry_time=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            dwell_time_sec=1.0,
            trajectory=[],
            is_confirmed=True,
        )

        obj2 = TrackedObject(
            track_id=102,
            camera_id=cam1.camera_id,
            class_id=5,
            class_name="bus",
            confidence=0.88,
            bbox=[v2_x1 / fw, v2_y1 / fh, (v2_x2 - v2_x1) / fw, (v2_y2 - v2_y1) / fh],
            center=((v2_x1 + v2_x2) / (2 * fw), (v2_y1 + v2_y2) / (2 * fh)),
            entry_time=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            dwell_time_sec=1.0,
            trajectory=[],
            is_confirmed=True,
        )

        # Frame 1: Initial detection
        await agent1._process_anpr_intelligence(frame, [obj1, obj2])
        # Frame 2: Second detection to confirm multi-frame tracker
        agent1.last_anpr_process_times.clear()  # Clear throttle for testing
        await agent1._process_anpr_intelligence(frame, [obj1, obj2])

        # Verify DB records for CAM-01
        records_cam1 = db_session.query(ANPRResult).filter(ANPRResult.camera_id == cam1.id).all()
        assert len(records_cam1) == 2, f"Expected 2 records (1 for car, 1 for bus), found {len(records_cam1)}"

        rec_car = [r for r in records_cam1 if r.vehicle_type == "CAR"][0]
        rec_bus = [r for r in records_cam1 if r.vehicle_type == "BUS"][0]

        # Verify Car (with real plate):
        assert rec_car.plate_number is not None
        assert "KA" in rec_car.plate_number
        assert rec_car.ocr_confidence >= ANPR_OCR_CONFIDENCE_THRESHOLD
        assert rec_car.status == "CONFIRMED"
        assert rec_car.camera_name == cam1.name
        assert rec_car.camera_location == cam1.location
        assert rec_car.snapshot_url is not None

        # Verify Bus (without plate):
        # Must be genuine NULL in database, NOT a fake string
        assert rec_bus.plate_number is None, f"Expected NULL plate_number for unreadable bus, got {rec_bus.plate_number}"
        assert rec_bus.ocr_confidence == 0.0
        assert rec_bus.status == "UNCERTAIN"
        assert rec_bus.plate_bbox is None, f"Expected None plate_bbox when no plate localized, got {rec_bus.plate_bbox}"
        assert rec_bus.camera_location == cam1.location

        # ─── Deduplication Test ───────────────────────────────────────────────
        # Process a 3rd frame: must NOT insert duplicate records for the same tracks
        agent1.last_anpr_process_times.clear()
        await agent1._process_anpr_intelligence(frame, [obj1, obj2])
        records_after = db_session.query(ANPRResult).filter(ANPRResult.camera_id == cam1.id).all()
        assert len(records_after) == 2, "Deduplication failed: duplicate records were created for the same tracks"

        # ─── Multi-Camera Independence Test ───────────────────────────────────
        # CAM-02 detects a truck with track_id 201
        obj_truck = TrackedObject(
            track_id=201,
            camera_id=cam2.camera_id,
            class_id=7,
            class_name="truck",
            confidence=0.91,
            bbox=[0.1, 0.2, 0.5, 0.5],
            center=(0.35, 0.45),
            entry_time=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            dwell_time_sec=1.0,
            trajectory=[],
            is_confirmed=True,
        )
        await agent2._process_anpr_intelligence(frame, [obj_truck])

        records_cam2 = db_session.query(ANPRResult).filter(ANPRResult.camera_id == cam2.id).all()
        assert len(records_cam2) == 1
        assert records_cam2[0].camera_id == cam2.id
        assert records_cam2[0].camera_name == cam2.name
        assert records_cam2[0].camera_location == cam2.location
        assert records_cam2[0].vehicle_type == "TRUCK"

        # Ensure CAM-01 records were not touched
        assert db_session.query(ANPRResult).filter(ANPRResult.camera_id == cam1.id).count() == 2

    finally:
        # Cleanup test records
        agent1.cleanup_live_session()
        agent2.cleanup_live_session()
        db_session.query(ANPRResult).filter(ANPRResult.camera_id.in_([cam1.id, cam2.id])).delete(synchronize_session=False)
        db_session.delete(cam1)
        db_session.delete(cam2)
        db_session.commit()
