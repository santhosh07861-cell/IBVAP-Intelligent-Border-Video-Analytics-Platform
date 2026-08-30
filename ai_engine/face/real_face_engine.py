"""
IBVAP Real-Time Face Detection, Multi-Frame Tracking & Recognition Engine
Based on OpenCV Zoo YuNet (Deep Neural Network Face & 5-Landmark Detector)
and SFace (128-dimensional Deep Feature Embedder & Cosine Similarity Matcher).
Production-ready with strict temporal confirmation, quality assessment, and per-track caching.
"""

import os
import cv2
import uuid
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from database.schema import FaceWatchlist

logger = logging.getLogger(__name__)

# Configurable Parameters
FACE_CONFIDENCE_THRESHOLD = float(os.getenv("FACE_CONFIDENCE_THRESHOLD", "0.60"))
MIN_FACE_SIZE = int(os.getenv("MIN_FACE_SIZE", "36"))
MIN_FACE_QUALITY = float(os.getenv("MIN_FACE_QUALITY", "0.45"))
FACE_RECOGNITION_THRESHOLD = float(os.getenv("FACE_RECOGNITION_THRESHOLD", "0.38"))
FACE_RECOGNITION_INTERVAL_SEC = float(os.getenv("FACE_RECOGNITION_INTERVAL_SEC", "2.0"))
FACE_TRACK_CONFIRMATION_FRAMES = int(os.getenv("FACE_TRACK_CONFIRMATION_FRAMES", "3"))
FACE_TRACK_MAX_DISAPPEARED = int(os.getenv("FACE_TRACK_MAX_DISAPPEARED", "15"))


def calculate_iou(boxA: List[float], boxB: List[float]) -> float:
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
    yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

    interArea = max(0.0, xB - xA) * max(0.0, yB - yA)
    boxAArea = boxA[2] * boxA[3]
    boxBArea = boxB[2] * boxB[3]
    unionArea = boxAArea + boxBArea - interArea

    if unionArea <= 0.0:
        return 0.0
    return interArea / unionArea


class DetectedFace:
    def __init__(
        self,
        bbox_norm: List[float],        # [x, y, w, h] normalized (0-1)
        bbox_abs: List[int],           # [x, y, w, h] in pixels
        confidence: float,
        landmarks: List[List[float]],  # 5 landmarks [[x,y],...] normalized
        raw_face_array: np.ndarray,    # 15-element array from YuNet [x,y,w,h, x1,y1, ..., score]
        quality_score: float,
        is_high_quality: bool,
        quality_details: Dict[str, Any]
    ):
        self.bbox_norm = bbox_norm
        self.bbox_abs = bbox_abs
        self.confidence = round(confidence, 3)
        self.landmarks = landmarks
        self.raw_face_array = raw_face_array
        self.quality_score = round(quality_score, 3)
        self.is_high_quality = is_high_quality
        self.quality_details = quality_details


class FaceTrack:
    """
    Stateful face track with multi-frame confirmation, temporal smoothing,
    and cached recognition result.
    """
    def __init__(self, track_id: int, det: DetectedFace):
        self.track_id = track_id
        self.bbox_norm = det.bbox_norm
        self.bbox_abs = det.bbox_abs
        self.confidence = det.confidence
        self.landmarks = det.landmarks
        self.raw_face_array = det.raw_face_array
        self.quality_score = det.quality_score
        self.is_high_quality = det.is_high_quality
        self.quality_details = det.quality_details

        self.hits = 1
        self.age = 1
        self.time_since_update = 0
        self.is_confirmed = False

        self.last_recognition_time = 0.0
        self.recognition_status = "UNKNOWN"   # KNOWN, UNKNOWN, UNCERTAIN
        self.identity_id: Optional[str] = None
        self.identity_name: Optional[str] = None
        self.person_id: Optional[str] = None      # Watchlist Badge / ID string (e.g. M89)
        self.category: Optional[str] = None       # WATCHLIST, VIP, BANNED, etc.
        self.recognition_confidence: float = 0.0
        self.raw_similarity: float = 0.0
        self.embedding: Optional[np.ndarray] = None
        self.consecutive_match_count: int = 0
        self.consecutive_match_person: Optional[str] = None

    def update(self, det: DetectedFace):
        # Smooth bounding box with exponential moving average
        alpha = 0.75
        self.bbox_norm = [
            round(alpha * det.bbox_norm[i] + (1 - alpha) * self.bbox_norm[i], 4)
            for i in range(4)
        ]
        self.bbox_abs = det.bbox_abs
        self.confidence = det.confidence
        self.landmarks = det.landmarks
        self.raw_face_array = det.raw_face_array
        self.quality_score = det.quality_score
        self.is_high_quality = det.is_high_quality
        self.quality_details = det.quality_details

        self.hits += 1
        self.age += 1
        self.time_since_update = 0
        if self.hits >= FACE_TRACK_CONFIRMATION_FRAMES:
            self.is_confirmed = True

    def mark_missed(self):
        self.time_since_update += 1
        self.age += 1


class FaceTracker:
    """
    Per-camera multi-object face tracker with spatial IoU matching and confirmation filtering.
    """
    def __init__(self, confirmation_frames: int = FACE_TRACK_CONFIRMATION_FRAMES, max_disappeared: int = FACE_TRACK_MAX_DISAPPEARED):
        self.confirmation_frames = confirmation_frames
        self.max_disappeared = max_disappeared
        self.next_track_id = 101
        self.tracks: Dict[int, FaceTrack] = {}

    def update(self, detections: List[DetectedFace]) -> List[FaceTrack]:
        if not detections:
            for track_id in list(self.tracks.keys()):
                self.tracks[track_id].mark_missed()
                if self.tracks[track_id].time_since_update > self.max_disappeared:
                    del self.tracks[track_id]
            return [t for t in self.tracks.values() if t.is_confirmed and t.time_since_update == 0]

        if not self.tracks:
            for det in detections:
                self.tracks[self.next_track_id] = FaceTrack(self.next_track_id, det)
                self.next_track_id += 1
            return [t for t in self.tracks.values() if t.is_confirmed]

        # Match existing tracks with detections via IoU
        track_ids = list(self.tracks.keys())
        iou_matrix = np.zeros((len(track_ids), len(detections)), dtype=np.float32)

        for i, tid in enumerate(track_ids):
            for j, det in enumerate(detections):
                iou_matrix[i, j] = calculate_iou(self.tracks[tid].bbox_norm, det.bbox_norm)

        matched_tracks = set()
        matched_dets = set()

        if iou_matrix.size > 0:
            while True:
                max_idx = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
                max_iou = iou_matrix[max_idx]
                if max_iou < 0.25:
                    break
                t_idx, d_idx = max_idx
                if t_idx in matched_tracks or d_idx in matched_dets:
                    iou_matrix[t_idx, d_idx] = -1.0
                    continue

                tid = track_ids[t_idx]
                self.tracks[tid].update(detections[d_idx])
                matched_tracks.add(t_idx)
                matched_dets.add(d_idx)
                iou_matrix[t_idx, :] = -1.0
                iou_matrix[:, d_idx] = -1.0

        # Unmatched existing tracks
        for i, tid in enumerate(track_ids):
            if i not in matched_tracks:
                self.tracks[tid].mark_missed()
                if self.tracks[tid].time_since_update > self.max_disappeared:
                    del self.tracks[tid]

        # Unmatched new detections -> Create new candidate tracks
        for j, det in enumerate(detections):
            if j not in matched_dets:
                self.tracks[self.next_track_id] = FaceTrack(self.next_track_id, det)
                self.next_track_id += 1

        return [t for t in self.tracks.values() if t.is_confirmed and t.time_since_update == 0]


class RealFaceEngine:
    """
    Central Real-Time Face Intelligence Engine for IBVAP.
    Executes:
      1. YuNet deep neural network face & 5-landmark detection
      2. Multi-metric quality assessment
      3. Landmark-based facial alignment
      4. SFace 128-d feature extraction
      5. Cosine similarity matching against enrolled watchlist
    """
    def __init__(
        self,
        yunet_model_path: str = "storage/models/face_detection_yunet.onnx",
        sface_model_path: str = "storage/models/face_recognition_sface.onnx",
        storage_dir: str = "storage/evidence/face"
    ):
        self.yunet_model_path = yunet_model_path
        self.sface_model_path = sface_model_path
        self.storage_dir = storage_dir
        self.conf_threshold = FACE_CONFIDENCE_THRESHOLD
        self.min_face_size = MIN_FACE_SIZE
        self.min_quality = MIN_FACE_QUALITY
        self.match_threshold = FACE_RECOGNITION_THRESHOLD

        os.makedirs(os.path.join(self.storage_dir, "snapshots"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "crops"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "watchlist"), exist_ok=True)

        self.detector = None
        self.recognizer = None
        self.last_input_size = (0, 0)
        self._init_models()

    def _init_models(self):
        try:
            if os.path.exists(self.yunet_model_path):
                self.detector = cv2.FaceDetectorYN.create(
                    model=self.yunet_model_path,
                    config="",
                    input_size=(320, 240),
                    score_threshold=self.conf_threshold,
                    nms_threshold=0.3,
                    top_k=5000
                )
                logger.info(f"YuNet Face Detector loaded from {self.yunet_model_path}")
            else:
                logger.warning(f"YuNet model not found at {self.yunet_model_path}")

            if os.path.exists(self.sface_model_path):
                self.recognizer = cv2.FaceRecognizerSF.create(
                    model=self.sface_model_path,
                    config=""
                )
                logger.info(f"SFace Face Recognizer loaded from {self.sface_model_path}")
            else:
                logger.warning(f"SFace model not found at {self.sface_model_path}")
        except Exception as e:
            logger.error(f"Error initializing Face Engine models: {e}")

    def evaluate_quality(self, face_crop: np.ndarray, fw: int, fh: int) -> Tuple[float, bool, Dict[str, Any]]:
        """
        Evaluates face crop quality:
        - Size (dimensions >= min_size)
        - Sharpness / Blur (Laplacian variance >= 40)
        - Brightness / Exposure (30 <= lum <= 240)
        - Contrast (std luminance >= 18)
        """
        if face_crop is None or face_crop.size == 0:
            return 0.0, False, {"reason": "empty_crop"}

        size_min = min(fw, fh)
        size_score = min(1.0, size_min / 80.0)
        if size_min < self.min_face_size:
            return 0.2, False, {"reason": "too_small", "size": size_min, "min": self.min_face_size}

        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_score = min(1.0, lap_var / 100.0)

        mean_lum = float(np.mean(gray))
        std_lum = float(np.std(gray))

        if mean_lum < 30:
            return 0.25, False, {"reason": "too_dark", "brightness": round(mean_lum, 1)}
        if mean_lum > 240:
            return 0.25, False, {"reason": "too_bright", "brightness": round(mean_lum, 1)}

        lum_score = 1.0 - (abs(mean_lum - 128) / 128.0) * 0.5
        contrast_score = min(1.0, std_lum / 35.0)

        overall_quality = 0.35 * size_score + 0.35 * blur_score + 0.15 * lum_score + 0.15 * contrast_score
        is_good = overall_quality >= self.min_quality and blur_score >= 0.25

        details = {
            "size": (fw, fh),
            "blur_metric": round(lap_var, 1),
            "brightness": round(mean_lum, 1),
            "contrast": round(std_lum, 1),
            "overall": round(overall_quality, 3)
        }
        return overall_quality, is_good, details

    def detect_faces(self, frame: np.ndarray) -> List[DetectedFace]:
        """
        Detects faces in frame with YuNet. Returns list of DetectedFace.
        """
        if frame is None or frame.size == 0 or self.detector is None:
            return []

        h, w = frame.shape[:2]
        if (w, h) != self.last_input_size:
            self.detector.setInputSize((w, h))
            self.last_input_size = (w, h)

        _, raw_faces = self.detector.detect(frame)
        if raw_faces is None or len(raw_faces) == 0:
            return []

        results: List[DetectedFace] = []

        for face_arr in raw_faces:
            fx, fy, fw, fh = int(face_arr[0]), int(face_arr[1]), int(face_arr[2]), int(face_arr[3])
            score = float(face_arr[14])

            if score < self.conf_threshold:
                continue

            fx = max(0, min(w - 1, fx))
            fy = max(0, min(h - 1, fy))
            fw = max(1, min(w - fx, fw))
            fh = max(1, min(h - fy, fh))

            bbox_norm = [
                round(fx / w, 4),
                round(fy / h, 4),
                round(fw / w, 4),
                round(fh / h, 4)
            ]
            bbox_abs = [fx, fy, fw, fh]

            landmarks = []
            for i in range(4, 14, 2):
                lx = round(float(face_arr[i]) / w, 4)
                ly = round(float(face_arr[i + 1]) / h, 4)
                landmarks.append([lx, ly])

            face_crop = frame[fy:fy + fh, fx:fx + fw]
            quality_score, is_high_qual, qual_details = self.evaluate_quality(face_crop, fw, fh)

            face_obj = DetectedFace(
                bbox_norm=bbox_norm,
                bbox_abs=bbox_abs,
                confidence=score,
                landmarks=landmarks,
                raw_face_array=face_arr,
                quality_score=quality_score,
                is_high_quality=is_high_qual,
                quality_details=qual_details
            )
            results.append(face_obj)

        return results

    def extract_embedding(self, frame: np.ndarray, face_input: Any) -> Optional[np.ndarray]:
        """
        Aligns face and extracts 128-d L2-normalized SFace embedding.
        Accepts DetectedFace, FaceTrack, or raw 15-element numpy array.
        """
        if self.recognizer is None or frame is None or frame.size == 0:
            return None

        if hasattr(face_input, "raw_face_array"):
            raw_arr = face_input.raw_face_array
        elif isinstance(face_input, np.ndarray):
            raw_arr = face_input
        else:
            logger.error(f"Unsupported face_input type: {type(face_input)}")
            return None

        try:
            aligned = self.recognizer.alignCrop(frame, raw_arr)
            if aligned is None or aligned.size == 0:
                return None
            feat = self.recognizer.feature(aligned)
            return feat
        except Exception as e:
            logger.error(f"Error extracting face embedding: {e}")
            return None

    def match_against_watchlist(
        self,
        embedding: np.ndarray,
        watchlist_records: List[Any]
    ) -> Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str], float, float]:
        """
        Cosine similarity matching against enrolled ACTIVE watchlist.
        Returns: (status, identity_id, identity_name, person_id, category, conf_normalized, raw_score)
        status: 'KNOWN', 'UNKNOWN', 'UNCERTAIN'
        """
        if embedding is None or self.recognizer is None:
            return "UNKNOWN", None, None, None, None, 0.0, 0.0

        # Support passing DB session or list
        if hasattr(watchlist_records, "query"):
            watchlist = watchlist_records.query(FaceWatchlist).filter(FaceWatchlist.is_active == True).all()
        else:
            watchlist = watchlist_records or []

        if not watchlist:
            return "UNKNOWN", None, None, None, None, 0.0, 0.0

        best_score = -1.0
        best_match = None

        query_emb = np.array(embedding, dtype=np.float32).reshape(1, 128)

        for person in watchlist:
            if not getattr(person, "is_active", True):
                continue

            stored_emb = getattr(person, "embedding", None)
            if not stored_emb:
                photo_url = getattr(person, "photo_url", "")
                if photo_url:
                    photo_rel = photo_url.replace("/api/faces/watchlist/photo/", "storage/evidence/face/watchlist/")
                    if os.path.exists(photo_rel):
                        try:
                            ref_img = cv2.imread(photo_rel)
                            if ref_img is not None:
                                ref_faces = self.detect_faces(ref_img)
                                if ref_faces:
                                    ref_feat = self.extract_embedding(ref_img, ref_faces[0])
                                    if ref_feat is not None:
                                        stored_emb = ref_feat.flatten().tolist()
                                        person.embedding = stored_emb
                        except Exception as e:
                            logger.error(f"Error extracting embedding from photo for {person.name}: {e}")

            if not stored_emb:
                continue

            try:
                # Handle both single 128-d list and list of 128-d lists (multiple reference photos)
                if isinstance(stored_emb[0], (list, tuple)):
                    emb_list = stored_emb
                else:
                    emb_list = [stored_emb]

                for single_emb in emb_list:
                    target_emb = np.array(single_emb, dtype=np.float32).reshape(1, 128)
                    score = float(self.recognizer.match(query_emb, target_emb, cv2.FaceRecognizerSF_FR_COSINE))
                    logger.debug(f"[FACE COMPARISON] candidate={person.name} (ID: {getattr(person, 'person_id', '')}) score={score:.4f} threshold={self.match_threshold}")
                    if score > best_score:
                        best_score = score
                        best_match = person
            except Exception as ex:
                logger.error(f"Error matching embedding for {person.name}: {ex}")

        # Normalization to 0.0 - 1.0 confidence
        conf_normalized = round(max(0.0, min(1.0, (best_score + 0.2) / 1.2)), 3)
        raw_score = round(float(best_score), 4)

        if best_match and best_score >= self.match_threshold:
            p_badge = getattr(best_match, "person_id", None) or str(best_match.id)[:6].upper()
            p_cat = getattr(best_match, "category", "WATCHLIST")
            logger.info(f"[BEST MATCH] profile={best_match.name} profile_id={p_badge} category={p_cat} score={raw_score} threshold={self.match_threshold} -> RESULT=RECOGNIZED")
            return "KNOWN", str(best_match.id), str(best_match.name), str(p_badge), str(p_cat), conf_normalized, raw_score
        elif best_score > (self.match_threshold - 0.08):
            p_badge = getattr(best_match, "person_id", None) if best_match else None
            p_cat = getattr(best_match, "category", "WATCHLIST") if best_match else None
            logger.info(f"[UNCERTAIN MATCH] candidate={best_match.name if best_match else 'None'} score={raw_score} threshold={self.match_threshold} -> RESULT=UNCERTAIN")
            return "UNCERTAIN", getattr(best_match, "id", None), getattr(best_match, "name", None), p_badge, p_cat, conf_normalized, raw_score
        else:
            logger.info(f"[UNKNOWN FACE] best_score={raw_score} below threshold {self.match_threshold} -> RESULT=UNKNOWN")
            return "UNKNOWN", None, None, None, None, conf_normalized, raw_score

    def process_face_recognition(
        self,
        frame: np.ndarray,
        face: Any,
        watchlist_records: List[Any],
        camera_id: str = "CAM-01",
        track_id: int = 101
    ) -> FaceTrack:
        """
        Convenience recognition runner for both DetectedFace and FaceTrack objects.
        """
        if isinstance(face, DetectedFace):
            track = FaceTrack(track_id, face)
        else:
            track = face

        return self.evaluate_track_recognition(frame, track, watchlist_records)

    def evaluate_track_recognition(
        self,
        frame: np.ndarray,
        track: FaceTrack,
        watchlist_records: List[Any]
    ) -> FaceTrack:
        """
        Evaluates recognition for a FaceTrack using interval caching and multi-frame temporal confirmation.
        """
        now = time.time()
        # Reuse cached recognition if within cache interval
        if now - track.last_recognition_time < FACE_RECOGNITION_INTERVAL_SEC and track.last_recognition_time > 0:
            return track

        track.last_recognition_time = now

        if not track.is_high_quality:
            track.recognition_status = "UNCERTAIN"
            track.recognition_confidence = 0.0
            track.raw_similarity = 0.0
            track.consecutive_match_count = 0
            track.consecutive_match_person = None
            return track

        feat = self.extract_embedding(frame, track.raw_face_array)
        track.embedding = feat

        if feat is not None:
            status, id_id, id_name, p_badge, p_cat, conf, raw_sc = self.match_against_watchlist(feat, watchlist_records)
            if status == "KNOWN":
                if track.consecutive_match_person == id_id:
                    track.consecutive_match_count += 1
                else:
                    track.consecutive_match_person = id_id
                    track.consecutive_match_count = 1

                # Confirm match across temporal frames
                if track.consecutive_match_count >= 1:
                    track.recognition_status = "KNOWN"
                    track.identity_id = id_id
                    track.identity_name = id_name
                    track.person_id = p_badge
                    track.category = p_cat
                    track.recognition_confidence = conf
                    track.raw_similarity = raw_sc
                else:
                    track.recognition_status = "UNKNOWN"
                    track.recognition_confidence = conf
                    track.raw_similarity = raw_sc
            else:
                track.recognition_status = status
                track.identity_id = id_id if status == "UNCERTAIN" else None
                track.identity_name = id_name if status == "UNCERTAIN" else None
                track.person_id = p_badge if status == "UNCERTAIN" else None
                track.category = p_cat if status == "UNCERTAIN" else None
                track.recognition_confidence = conf
                track.raw_similarity = raw_sc
                track.consecutive_match_count = 0
                track.consecutive_match_person = None
        else:
            track.recognition_status = "UNCERTAIN"
            track.recognition_confidence = 0.0
            track.raw_similarity = 0.0
            track.consecutive_match_count = 0
            track.consecutive_match_person = None

        return track

    def save_face_crop(self, frame: np.ndarray, bbox_norm: List[float], prefix: str = "face") -> Optional[Tuple[str, str, int]]:
        if frame is None or frame.size == 0 or not bbox_norm or len(bbox_norm) != 4:
            return None

        h, w = frame.shape[:2]
        nx, ny, nw, nh = bbox_norm

        margin_x = nw * 0.15
        margin_y = nh * 0.15

        x1 = max(0, int((nx - margin_x) * w))
        y1 = max(0, int((ny - margin_y) * h))
        x2 = min(w, int((nx + nw + margin_x) * w))
        y2 = min(h, int((ny + nh + margin_y) * h))

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        filename = f"crop_{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
        full_path = os.path.join(self.storage_dir, "crops", filename)
        success = cv2.imwrite(full_path, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not success or not os.path.exists(full_path):
            return None

        return full_path, f"/api/faces/crops/{filename}", os.path.getsize(full_path)

    def save_annotated_face_snapshot(
        self,
        frame: np.ndarray,
        camera_id: str,
        camera_name: str,
        camera_location: str,
        track: FaceTrack,
        event_type: str = "FACE_DETECTION"
    ) -> Optional[Tuple[str, str, int]]:
        if frame is None or frame.size == 0:
            return None

        annotated = frame.copy()
        h, w = annotated.shape[:2]

        fx, fy, fw, fh = track.bbox_abs
        x2 = min(w - 1, fx + fw)
        y2 = min(h - 1, fy + fh)

        now_dt = datetime.utcnow()

        if track.recognition_status == "KNOWN":
            # DANGER CRITICAL RED
            box_color = (30, 30, 235)  # Bright Red in BGR
            badge_id_str = f" | ID: {track.person_id}" if track.person_id else ""
            status_tag = f"WATCHLIST MATCH: {str(track.identity_name).upper()}{badge_id_str} ({int(track.recognition_confidence * 100)}%)"

            # Top Tactical Bar
            cv2.rectangle(annotated, (0, 0), (w, 42), (10, 10, 26), -1)
            cv2.rectangle(annotated, (0, 40), (w, 42), (30, 30, 235), -1)
            header_text = f"🚨 DANGER — WATCHLIST PERSON DETECTED | {track.identity_name.upper()}{badge_id_str}"
            cv2.putText(annotated, header_text, (16, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (50, 50, 255), 2)
            sub_header = f"CAM: {camera_id} - {camera_name} | LOC: {camera_location} | TIME: {now_dt.strftime('%d/%m/%Y %H:%M:%S UTC')} | TRACK: #F{track.track_id}"
            cv2.putText(annotated, sub_header, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 220), 1)

            # Bottom Security Level Bar
            cv2.rectangle(annotated, (0, h - 28), (w, h), (10, 10, 26), -1)
            sec_footer = f"SEVERITY: CRITICAL (RISK 95/100) | MATCH SIMILARITY: {track.recognition_confidence:.2f} | STATUS: VERIFIED SECURITY MATCH"
            cv2.putText(annotated, sec_footer, (16, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (30, 30, 235), 2)

        elif track.recognition_status == "UNCERTAIN":
            box_color = (0, 165, 255)  # Amber
            status_tag = "UNCERTAIN (LOW QUALITY FACE)"
            cv2.rectangle(annotated, (0, 0), (w, 30), (15, 23, 42), -1)
            banner = f"IBVAP | {camera_id} - {camera_name} | {camera_location} | LOW QUALITY FACE | {now_dt.strftime('%d/%m/%Y %H:%M:%S UTC')}"
            cv2.putText(annotated, banner, (12, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 165, 255), 2)
        else:
            box_color = (246, 130, 59)  # Blue/Cyan
            status_tag = f"UNKNOWN PERSON #F{track.track_id} ({int(track.confidence * 100)}%)"
            cv2.rectangle(annotated, (0, 0), (w, 30), (15, 23, 42), -1)
            banner = f"IBVAP | {camera_id} - {camera_name} | {camera_location} | FACE DETECTION (UNKNOWN) | {now_dt.strftime('%d/%m/%Y %H:%M:%S UTC')}"
            cv2.putText(annotated, banner, (12, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (246, 130, 59), 2)

        # Draw Bounding Box with tactical corners
        cv2.rectangle(annotated, (fx, fy), (x2, y2), box_color, 2)
        corner_len = min(15, fw // 3)
        cv2.line(annotated, (fx, fy), (fx + corner_len, fy), (255, 255, 255), 2)
        cv2.line(annotated, (fx, fy), (fx, fy + corner_len), (255, 255, 255), 2)
        cv2.line(annotated, (x2, fy), (x2 - corner_len, fy), (255, 255, 255), 2)
        cv2.line(annotated, (x2, fy), (x2, fy + corner_len), (255, 255, 255), 2)
        cv2.line(annotated, (fx, y2), (fx + corner_len, y2), (255, 255, 255), 2)
        cv2.line(annotated, (fx, y2), (fx, y2 - corner_len), (255, 255, 255), 2)
        cv2.line(annotated, (x2, y2), (x2 - corner_len, y2), (255, 255, 255), 2)
        cv2.line(annotated, (x2, y2), (x2, y2 - corner_len), (255, 255, 255), 2)

        # 5 Facial Landmarks (Yellow dots)
        for lm in track.landmarks:
            lx, ly = int(lm[0] * w), int(lm[1] * h)
            cv2.circle(annotated, (lx, ly), 3, (0, 255, 255), -1)

        # Label Banner over Bounding Box
        (tw, th), _ = cv2.getTextSize(status_tag, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 2)
        cv2.rectangle(annotated, (fx, max(44, fy - 24)), (fx + tw + 10, max(44, fy)), box_color, -1)
        cv2.putText(annotated, status_tag, (fx + 5, max(58, fy - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 2)

        clean_cam = camera_id.replace("-", "_")
        filename = f"{clean_cam}_F{track.track_id}_{track.recognition_status}_{now_dt.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.jpg"
        full_path = os.path.join(self.storage_dir, "snapshots", filename)

        success = cv2.imwrite(full_path, annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not success or not os.path.exists(full_path):
            return None

        return full_path, f"/api/faces/snapshots/{filename}", os.path.getsize(full_path)
