"""
IBVAP Multi-Object Tracker (MOT)
================================
Maintains persistent, stable object identities across real-time video frames.
Supports multi-class tracking with spatial proximity, IoU/center distance matching,
temporal stability confirmation, velocity computation, directional vectors,
movement state classification, and class consistency.
"""

import math
import logging
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any
from collections import Counter
import pydantic

from backend.config import TRACK_CONFIRMATION_FRAMES, TRACK_MAX_DISAPPEARED

logger = logging.getLogger(__name__)


def compute_cardinal_direction(dx: float, dy: float) -> str:
    """Computes cardinal/intercardinal direction from movement delta vector."""
    if math.hypot(dx, dy) < 0.003:
        return "STATIONARY"
    # Angle in degrees (-180 to 180) where negative dy is upwards (NORTH)
    angle = math.degrees(math.atan2(-dy, dx))
    if -22.5 <= angle < 22.5:
        return "EAST"
    elif 22.5 <= angle < 67.5:
        return "NORTH_EAST"
    elif 67.5 <= angle < 112.5:
        return "NORTH"
    elif 112.5 <= angle < 157.5:
        return "NORTH_WEST"
    elif angle >= 157.5 or angle < -157.5:
        return "WEST"
    elif -157.5 <= angle < -112.5:
        return "SOUTH_WEST"
    elif -112.5 <= angle < -67.5:
        return "SOUTH"
    elif -67.5 <= angle < -22.5:
        return "SOUTH_EAST"
    return "STATIONARY"


class TrackedObject(pydantic.BaseModel):
    track_id: int
    camera_id: str
    class_id: int = 0
    class_name: str
    confidence: float
    bbox: List[float]  # [x, y, w, h] normalized
    previous_bbox: Optional[List[float]] = None
    center: Tuple[float, float]
    previous_centroid: Optional[Tuple[float, float]] = None
    entry_time: datetime
    last_seen: datetime
    dwell_time_sec: float
    trajectory: List[Tuple[float, float, str]]  # list of (center_x, center_y, iso_timestamp)
    hits: int = 1
    is_confirmed: bool = False
    is_fallback: bool = False
    movement_delta: float = 0.0
    velocity: float = 0.0
    direction: str = "STATIONARY"
    movement_state: str = "STATIONARY"  # MOVING, SLOW_MOVEMENT, STATIONARY, CROUCHING


class MultiObjectTracker:
    def __init__(
        self,
        max_disappeared: int = TRACK_MAX_DISAPPEARED,
        max_distance: float = 0.24,
        confirmation_frames: int = TRACK_CONFIRMATION_FRAMES
    ):
        self.next_track_id = 101
        self.tracks: Dict[int, TrackedObject] = {}
        self.disappeared: Dict[int, int] = {}
        self.class_votes: Dict[int, Counter] = {}  # track_id -> Counter of class names
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance
        self.confirmation_frames = confirmation_frames

    def update(self, camera_id: str, raw_detections: List[Any]) -> List[TrackedObject]:
        now = datetime.utcnow()
        now_str = now.isoformat()

        if len(raw_detections) == 0:
            for track_id in list(self.disappeared.keys()):
                self.disappeared[track_id] += 1
                if self.disappeared[track_id] > self.max_disappeared:
                    if track_id in self.tracks:
                        t = self.tracks[track_id]
                        logger.info(f"[TRACK_LOST] camera={camera_id} track_id={track_id} class={t.class_name} dwell_sec={t.dwell_time_sec}")
                        del self.tracks[track_id]
                    if track_id in self.disappeared:
                        del self.disappeared[track_id]
                    if track_id in self.class_votes:
                        del self.class_votes[track_id]
            return list(self.tracks.values())

        input_centers = []
        for det in raw_detections:
            bbox = det.bbox if hasattr(det, 'bbox') else det['bbox']
            cx = bbox[0] + bbox[2] / 2.0
            cy = bbox[1] + bbox[3] / 2.0
            input_centers.append((cx, cy))

        if len(self.tracks) == 0:
            for i, det in enumerate(raw_detections):
                self._register(camera_id, det, input_centers[i], now)
        else:
            track_ids = list(self.tracks.keys())
            track_centers = [self.tracks[tid].center for tid in track_ids]

            # Compute distance matrix between existing tracks and new detections
            D = []
            for tid, tc in zip(track_ids, track_centers):
                row = []
                track_cls = self.tracks[tid].class_name.lower()
                for ic, det in zip(input_centers, raw_detections):
                    det_cls = (det.class_name if hasattr(det, 'class_name') else det.get('class_name', '')).lower()
                    dist = math.hypot(tc[0] - ic[0], tc[1] - ic[1])
                    # Penalize distance if classes do not match (prevents person/object identity swaps)
                    if track_cls != det_cls:
                        dist += 0.25
                    row.append(dist)
                D.append(row)

            assigned_tracks = set()
            assigned_dets = set()

            # Greedy matching
            if len(D) > 0 and len(D[0]) > 0:
                rows = len(D)
                cols = len(D[0])
                flat_pairs = []
                for r in range(rows):
                    for c in range(cols):
                        flat_pairs.append((D[r][c], r, c))
                flat_pairs.sort(key=lambda x: x[0])

                for dist, r, c in flat_pairs:
                    if r in assigned_tracks or c in assigned_dets:
                        continue
                    if dist > self.max_distance:
                        continue

                    tid = track_ids[r]
                    det = raw_detections[c]
                    cx, cy = input_centers[c]

                    bbox = det.bbox if hasattr(det, 'bbox') else det['bbox']
                    confidence = det.confidence if hasattr(det, 'confidence') else det['confidence']
                    class_name = det.class_name if hasattr(det, 'class_name') else det['class_name']
                    class_id = det.class_id if hasattr(det, 'class_id') else det.get('class_id', 0)
                    is_fallback = det.is_fallback if hasattr(det, 'is_fallback') else det.get('is_fallback', False)

                    track = self.tracks[tid]
                    prev_cx, prev_cy = track.center
                    prev_bbox = list(track.bbox)

                    dx = cx - prev_cx
                    dy = cy - prev_cy
                    movement_delta = round(math.hypot(dx, dy), 4)

                    dt = max(0.01, (now - track.last_seen).total_seconds())
                    velocity = round(movement_delta / dt, 3)
                    direction = compute_cardinal_direction(dx, dy)

                    # Movement state determination
                    if prev_bbox and len(prev_bbox) == 4 and bbox[3] < 0.70 * prev_bbox[3]:
                        movement_state = "CROUCHING"
                    elif movement_delta >= 0.015:
                        movement_state = "MOVING"
                    elif movement_delta >= 0.003:
                        movement_state = "SLOW_MOVEMENT"
                    else:
                        movement_state = "STATIONARY"

                    track.previous_bbox = prev_bbox
                    track.previous_centroid = (prev_cx, prev_cy)
                    track.bbox = bbox
                    track.confidence = confidence
                    track.center = (cx, cy)
                    track.last_seen = now
                    track.dwell_time_sec = round((now - track.entry_time).total_seconds(), 1)
                    track.hits += 1
                    track.movement_delta = movement_delta
                    track.velocity = velocity
                    track.direction = direction
                    track.movement_state = movement_state

                    # Update class votes for temporal class stability
                    if tid not in self.class_votes:
                        self.class_votes[tid] = Counter()
                    self.class_votes[tid][class_name] += 1
                    majority_class = self.class_votes[tid].most_common(1)[0][0]
                    track.class_name = majority_class
                    track.class_id = class_id

                    if track.hits >= self.confirmation_frames:
                        track.is_confirmed = True

                    track.trajectory.append((round(cx, 3), round(cy, 3), now_str))
                    if len(track.trajectory) > 50:
                        track.trajectory = track.trajectory[-50:]

                    self.disappeared[tid] = 0
                    assigned_tracks.add(r)
                    assigned_dets.add(c)

                    logger.debug(f"[TRACK_UPDATED] camera={camera_id} track_id={tid} class={track.class_name} state={movement_state} delta={movement_delta:.4f} dir={direction}")

            # Unassigned tracks
            for r in range(len(track_ids)):
                if r not in assigned_tracks:
                    tid = track_ids[r]
                    self.disappeared[tid] += 1
                    if self.disappeared[tid] > self.max_disappeared:
                        if tid in self.tracks:
                            t = self.tracks[tid]
                            logger.info(f"[TRACK_LOST] camera={camera_id} track_id={tid} class={t.class_name} dwell_sec={t.dwell_time_sec}")
                            del self.tracks[tid]
                        if tid in self.disappeared:
                            del self.disappeared[tid]
                        if tid in self.class_votes:
                            del self.class_votes[tid]

            # Unassigned detections -> Register as new tracks
            for c in range(len(raw_detections)):
                if c not in assigned_dets:
                    self._register(camera_id, raw_detections[c], input_centers[c], now)

        return list(self.tracks.values())

    def _register(self, camera_id: str, det: Any, center: Tuple[float, float], now: datetime):
        bbox = det.bbox if hasattr(det, 'bbox') else det['bbox']
        confidence = det.confidence if hasattr(det, 'confidence') else det['confidence']
        class_name = det.class_name if hasattr(det, 'class_name') else det['class_name']
        class_id = det.class_id if hasattr(det, 'class_id') else det.get('class_id', 0)
        is_fallback = det.is_fallback if hasattr(det, 'is_fallback') else det.get('is_fallback', False)

        tid = self.next_track_id
        self.next_track_id += 1

        now_str = now.isoformat()
        is_conf = (1 >= self.confirmation_frames)
        track = TrackedObject(
            track_id=tid,
            camera_id=camera_id,
            class_id=class_id,
            class_name=class_name,
            bbox=bbox,
            previous_bbox=None,
            confidence=confidence,
            center=center,
            previous_centroid=None,
            entry_time=now,
            last_seen=now,
            dwell_time_sec=0.0,
            trajectory=[(round(center[0], 3), round(center[1], 3), now_str)],
            hits=1,
            is_confirmed=is_conf,
            is_fallback=is_fallback,
            movement_delta=0.0,
            velocity=0.0,
            direction="STATIONARY",
            movement_state="STATIONARY"
        )
        self.tracks[tid] = track
        self.disappeared[tid] = 0
        self.class_votes[tid] = Counter([class_name])
        logger.info(f"[TRACK_CREATED] camera={camera_id} track_id={tid} class={class_name} conf={confidence:.2f} bbox={[round(v, 3) for v in bbox]}")
