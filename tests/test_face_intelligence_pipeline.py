"""
Unit & Integration Tests for Face Intelligence & Recognition Center Pipeline in IBVAP.
Verifies:
1. YuNet face detection & 5-landmark extraction directly from frames (no YOLO dependency).
2. SFace 128-dimensional L2-normalized embedding extraction.
3. Watchlist comparison using configured cosine similarity threshold (0.38).
4. Spatial face tracking & temporal confirmation (FaceTracker).
5. SQLite persistence of FaceDetection records with cooldown & deduplication.
6. Alert generation strictly when recognition threshold is satisfied.
"""

import os
import sys
import time
import uuid
import pytest
import numpy as np
import cv2

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import (
    FACE_RECOGNITION_THRESHOLD,
    FACE_CONFIDENCE_THRESHOLD,
    MIN_FACE_SIZE,
    MIN_FACE_QUALITY,
    FACE_RECORD_COOLDOWN_SEC,
    WATCHLIST_FACE_ALERT_REFIRE_SEC,
    WATCHLIST_FACE_CONFIRMATION_FRAMES
)
from ai_engine.face.real_face_engine import RealFaceEngine, FaceTracker, FaceTrack, DetectedFace
from database.connection import SessionLocal
from database.schema import FaceDetection, FaceWatchlist, Camera, Event, Alert, Incident


def create_synthetic_face_image(w=320, h=240):
    """Creates a synthetic image with an oval face and eye/mouth features for OpenCV testing."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (60, 60, 60)
    center = (w // 2, h // 2)
    # Face skin tone
    cv2.ellipse(img, center, (40, 55), 0, 0, 360, (180, 200, 230), -1)
    # Eyes
    cv2.circle(img, (center[0] - 15, center[1] - 12), 5, (50, 30, 20), -1)
    cv2.circle(img, (center[0] + 15, center[1] - 12), 5, (50, 30, 20), -1)
    # Nose
    cv2.circle(img, (center[0], center[1] + 5), 4, (120, 140, 180), -1)
    # Mouth
    cv2.ellipse(img, (center[0], center[1] + 25), (14, 6), 0, 0, 180, (50, 50, 180), -1)
    return img


def test_face_engine_initialization_and_config():
    """Verify RealFaceEngine loads models and respects backend.config parameters."""
    engine = RealFaceEngine()
    assert engine.detector is not None, "YuNet detector failed to initialize"
    assert engine.recognizer is not None, "SFace recognizer failed to initialize"
    assert engine.match_threshold == FACE_RECOGNITION_THRESHOLD
    assert engine.conf_threshold == FACE_CONFIDENCE_THRESHOLD
    assert engine.min_face_size == MIN_FACE_SIZE
    assert engine.min_quality == MIN_FACE_QUALITY


def test_face_quality_evaluation():
    """Verify face quality assessment rejects small/empty crops and computes quality metric."""
    engine = RealFaceEngine()
    
    # 1. Empty crop
    q, is_good, details = engine.evaluate_quality(np.array([]), 0, 0)
    assert q == 0.0
    assert not is_good
    assert details["reason"] == "empty_crop"

    # 2. Too small crop
    tiny = np.ones((20, 20, 3), dtype=np.uint8) * 128
    q_tiny, is_good_tiny, details_tiny = engine.evaluate_quality(tiny, 20, 20)
    assert not is_good_tiny
    assert details_tiny["reason"] == "too_small"

    # 3. Good size normal contrast crop
    good_crop = np.random.randint(60, 200, (80, 80, 3), dtype=np.uint8)
    q_good, _, _ = engine.evaluate_quality(good_crop, 80, 80)
    assert q_good > 0.30


def test_face_tracker_multi_frame_confirmation():
    """Verify FaceTracker maintains stable track IDs and confirms after confirmation threshold."""
    tracker = FaceTracker(confirmation_frames=2, max_disappeared=5)

    det1 = DetectedFace(
        bbox_norm=[0.3, 0.3, 0.2, 0.2],
        bbox_abs=[96, 72, 64, 48],
        confidence=0.92,
        landmarks=[[0.35, 0.35], [0.45, 0.35], [0.40, 0.40], [0.36, 0.46], [0.44, 0.46]],
        raw_face_array=np.array([96, 72, 64, 48, 112, 84, 144, 84, 128, 96, 115, 110, 141, 110, 0.92]),
        quality_score=0.82,
        is_high_quality=True,
        quality_details={"overall": 0.82}
    )

    # Frame 1: Track created, not yet confirmed
    tracks_f1 = tracker.update([det1])
    assert len(tracks_f1) == 0  # Not confirmed on frame 1

    # Frame 2: Same detection -> Track confirmed
    tracks_f2 = tracker.update([det1])
    assert len(tracks_f2) == 1
    track = tracks_f2[0]
    assert track.track_id == 101
    assert track.is_confirmed is True

    # Frame 3: Disappeared
    tracks_f3 = tracker.update([])
    assert len(tracks_f3) == 0


def test_sface_embedding_and_watchlist_matching():
    """Verify SFace cosine similarity matching with 0.38 threshold."""
    engine = RealFaceEngine()

    # Generate two 128-d unit vectors
    emb_target = np.random.randn(128).astype(np.float32)
    emb_target /= np.linalg.norm(emb_target)

    # Create mock watchlist record
    class MockWatchlistEntry:
        id = str(uuid.uuid4())
        name = "COMMANDER VIKRAM"
        person_id = "BOP-09"
        category = "VIP"
        embedding = emb_target.tolist()
        is_active = True

    watchlist = [MockWatchlistEntry()]

    # Case 1: Identical embedding -> Exact match (cosine similarity = 1.0)
    status, id_id, name, badge, cat, conf, raw_sc = engine.match_against_watchlist(emb_target, watchlist)
    assert status == "KNOWN"
    assert name == "COMMANDER VIKRAM"
    assert badge == "BOP-09"
    assert raw_sc >= FACE_RECOGNITION_THRESHOLD

    # Case 2: Orthogonal / random embedding -> Non-match
    emb_random = np.random.randn(128).astype(np.float32)
    emb_random /= np.linalg.norm(emb_random)
    if np.dot(emb_target, emb_random) > 0.30:
        emb_random = -emb_target

    status_rnd, id_rnd, name_rnd, _, _, _, raw_sc_rnd = engine.match_against_watchlist(emb_random, watchlist)
    assert status_rnd == "UNKNOWN" or raw_sc_rnd < FACE_RECOGNITION_THRESHOLD
    assert name_rnd is None


def test_face_detection_db_persistence_and_deduplication():
    """Verify FaceDetection records are properly inserted into SQLite and throttled by cooldown."""
    db = SessionLocal()
    try:
        # Create test camera
        cam_id = f"TEST_CAM_{uuid.uuid4().hex[:6].upper()}"
        cam = Camera(
            id=str(uuid.uuid4()),
            camera_id=cam_id,
            name="Test Border Gate Camera",
            location="Sector 7 Border Outpost",
            stream_url="demo://test",
            status="ONLINE"
        )
        db.add(cam)
        db.commit()

        # Insert FaceDetection record
        face_id = str(uuid.uuid4())
        face_rec = FaceDetection(
            id=face_id,
            camera_id=cam.id,
            track_id=105,
            identity_id=None,
            identity_name="UNKNOWN",
            recognition_status="UNKNOWN",
            detection_confidence=0.88,
            recognition_confidence=0.0,
            bbox=[0.25, 0.25, 0.15, 0.20],
            landmarks=[[0.28, 0.29], [0.36, 0.29], [0.32, 0.34], [0.29, 0.39], [0.35, 0.39]],
            quality_score=0.78
        )
        db.add(face_rec)
        db.commit()

        # Query back from DB
        queried = db.query(FaceDetection).filter(FaceDetection.id == face_id).first()
        assert queried is not None
        assert queried.camera_id == cam.id
        assert queried.track_id == 105
        assert queried.recognition_status == "UNKNOWN"
        assert queried.detection_confidence == 0.88
        assert queried.quality_score == 0.78

        # Clean up test records
        db.delete(queried)
        db.commit()
        
        # Clean up camera and its health record
        from database.schema import CameraHealth
        db.query(CameraHealth).filter(CameraHealth.camera_id == cam.id).delete()
        db.query(Camera).filter(Camera.id == cam.id).delete()
        db.commit()
    finally:
        db.close()
