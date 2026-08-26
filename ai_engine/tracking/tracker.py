import math
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import pydantic

class TrackedObject(pydantic.BaseModel):
    track_id: int
    camera_id: str
    class_name: str
    bbox: List[float]  # [x, y, w, h] normalized
    confidence: float
    center: Tuple[float, float]
    entry_time: datetime
    last_seen: datetime
    dwell_time_sec: float
    trajectory: List[Tuple[float, float, str]]  # list of (center_x, center_y, iso_timestamp)
    is_fallback: bool = False

class MultiObjectTracker:
    def __init__(self, max_disappeared: int = 30, max_distance: float = 0.15):
        self.next_track_id = 101
        self.tracks: Dict[int, TrackedObject] = {}
        self.disappeared: Dict[int, int] = {}
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance

    def update(self, camera_id: str, raw_detections: List[dict]) -> List[TrackedObject]:
        now = datetime.utcnow()
        now_str = now.isoformat()

        if len(raw_detections) == 0:
            for track_id in list(self.disappeared.keys()):
                self.disappeared[track_id] += 1
                if self.disappeared[track_id] > self.max_disappeared:
                    del self.tracks[track_id]
                    del self.disappeared[track_id]
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
            for tc in track_centers:
                row = []
                for ic in input_centers:
                    dist = math.hypot(tc[0] - ic[0], tc[1] - ic[1])
                    row.append(dist)
                D.append(row)

            assigned_tracks = set()
            assigned_dets = set()

            # Greedy Hungarian-like matching
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
                    is_fallback = det.is_fallback if hasattr(det, 'is_fallback') else det.get('is_fallback', False)

                    track = self.tracks[tid]
                    track.bbox = bbox
                    track.confidence = confidence
                    track.center = (cx, cy)
                    track.last_seen = now
                    track.dwell_time_sec = round((now - track.entry_time).total_seconds(), 1)
                    track.trajectory.append((round(cx, 3), round(cy, 3), now_str))
                    if len(track.trajectory) > 50:
                        track.trajectory = track.trajectory[-50:]

                    self.disappeared[tid] = 0
                    assigned_tracks.add(r)
                    assigned_dets.add(c)

            # Unassigned tracks
            for r in range(len(track_ids)):
                if r not in assigned_tracks:
                    tid = track_ids[r]
                    self.disappeared[tid] += 1
                    if self.disappeared[tid] > self.max_disappeared:
                        del self.tracks[tid]
                        del self.disappeared[tid]

            # Unassigned detections -> Register as new tracks
            for c in range(len(raw_detections)):
                if c not in assigned_dets:
                    self._register(camera_id, raw_detections[c], input_centers[c], now)

        return list(self.tracks.values())

    def _register(self, camera_id: str, det: dict, center: Tuple[float, float], now: datetime):
        bbox = det.bbox if hasattr(det, 'bbox') else det['bbox']
        confidence = det.confidence if hasattr(det, 'confidence') else det['confidence']
        class_name = det.class_name if hasattr(det, 'class_name') else det['class_name']
        is_fallback = det.is_fallback if hasattr(det, 'is_fallback') else det.get('is_fallback', False)

        tid = self.next_track_id
        self.next_track_id += 1

        now_str = now.isoformat()
        track = TrackedObject(
            track_id=tid,
            camera_id=camera_id,
            class_name=class_name,
            bbox=bbox,
            confidence=confidence,
            center=center,
            entry_time=now,
            last_seen=now,
            dwell_time_sec=0.0,
            trajectory=[(round(center[0], 3), round(center[1], 3), now_str)],
            is_fallback=is_fallback
        )
        self.tracks[tid] = track
        self.disappeared[tid] = 0
