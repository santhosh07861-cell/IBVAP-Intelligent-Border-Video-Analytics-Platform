# IBVAP — SIH 2026 Problem Statement & Solution Mapping Document

**Project Name:** IBVAP – Intelligent Border Video Analytics Platform  
**Target Organization:** Border Security Forces (BSF) / Ministry of Home Affairs / SIH 2026 Evaluation  

---

## 1. Executive Summary

Traditional border security surveillance relies on conventional CCTV cameras deployed across Border Out Posts (BOPs), checkposts, and strategic border roads. These conventional cameras act strictly as passive video recording units, placing an overwhelming burden on security operators for continuous manual observation. Furthermore, specialized smart cameras with built-in Facial Recognition Systems (FRS) or Automatic Number Plate Recognition (ANPR) hardware are prohibitively expensive for large-scale deployment across remote border regions.

**IBVAP** is a **software-defined, hardware-agnostic AI surveillance platform** that transforms existing standard IP-based CCTV infrastructure into an intelligent, autonomous threat detection network without requiring specialized smart hardware.

---

## 2. Requirement-to-Feature Mapping Matrix

| SIH Problem Requirement | IBVAP Implementation & Module | Software Mechanism |
|---|---|---|
| **Eliminate Specialized Hardware** | [`video_engine/ingestion/source.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/video_engine/ingestion/source.py) | Ingests standard RTSP/ONVIF streams, MP4 files, or USB webcams via software frame processing. |
| **Human Detection & Tracking** | [`ai_engine/detection/yolo_detector.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/ai_engine/detection/yolo_detector.py)<br>[`ai_engine/tracking/tracker.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/ai_engine/tracking/tracker.py) | YOLO person detector coupled with ByteTrack/Centroid multi-object tracker managing unique Track IDs, trajectories, and dwell times. |
| **Vehicle Detection & Classification** | [`ai_engine/detection/yolo_detector.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/ai_engine/detection/yolo_detector.py) | Real-time classification of cars, trucks, buses, motorcycles, vans, and bicycles with bounding box confidence overlays. |
| **Face Detection** | [`ai_engine/face/face_engine.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/ai_engine/face/face_engine.py) | Software face detection extracting face bounding boxes without expensive proprietary FRS cameras. |
| **Automatic Number Plate Recognition (ANPR)** | [`ai_engine/anpr/anpr_engine.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/ai_engine/anpr/anpr_engine.py) | Automated vehicle plate region cropping, OpenCV grayscale/adaptive thresholding, and OCR text extraction. |
| **Virtual Fence Intrusion Detection** | [`event_engine/rules/virtual_fence.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/event_engine/rules/virtual_fence.py)<br>[`frontend/src/pages/ZoneEditor.tsx`](file:///Users/tejavathusanthosh/Downloads/IBVAP/frontend/src/pages/ZoneEditor.tsx) | Interactive visual zone canvas editor supporting polygon containment (Ray-casting) and line-crossing intrusion detection. |
| **Suspicious Activity & Loitering** | [`event_engine/behavior/loitering.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/event_engine/behavior/loitering.py) | Behavioral tracking enforcing configurable loitering thresholds, crowd density limits, and vehicle stopping alerts. |
| **Night-Time Movement Detection** | [`event_engine/behavior/loitering.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/event_engine/behavior/loitering.py)<br>[`event_engine/risk/scorer.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/event_engine/risk/scorer.py) | Automatic night-hour detection boosting threat weighting for movement occurring during high-risk night windows. |
| **Real-Time Alert & Event Logging** | [`backend/main.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/backend/main.py)<br>[`event_engine/correlation/correlator.py`](file:///Users/tejavathusanthosh/Downloads/IBVAP/event_engine/correlation/correlator.py) | Correlates raw detections into single managed Incidents with transparent 0–100 Risk Scores, streaming real-time alerts via WebSockets. |
| **Command Center Integration** | [`frontend/src/pages/Dashboard.tsx`](file:///Users/tejavathusanthosh/Downloads/IBVAP/frontend/src/pages/Dashboard.tsx) | Dense, dark-themed security command center dashboard with multi-camera grid views, Leaflet map overlays, and evidence management. |

---

## 3. Key SIH Innovations & Advantages

1. **Software-Defined Economy**: Saves up to 90% in hardware deployment costs by utilizing existing CCTV cameras at border outposts rather than replacing them with proprietary smart cameras.
2. **Transparent Operational Risk Score (0–100)**: Avoids false-alarm fatigue by combining multiple threat signals (e.g. `Night Mode (+20)` + `Restricted Zone (+30)` + `Fence Crossing (+30)` + `Loitering (+10)`) into a single normalized score.
3. **Remote Border Post Resilience**: Built with local SQLite/PostgreSQL edge storage and RTSP stream auto-reconnect backoff so edge processing continues even during satellite network disconnections.
4. **Complete SIH Demonstration Center**: Built-in 1-click evaluation workflow (`/demo`) that simulates end-to-end intrusion detection, alert generation, snapshot evidence capture, and incident resolution for live judging.

---

## 4. Quick Verification Instructions for Judges

1. Open `http://localhost:5173`.
2. Click **Administrator** quick-login (`admin` / `Admin Pass123!`).
3. Navigate to **SIH Demo Center** (`/demo`).
4. Click **"TRIGGER SIH INTRUSION WORKFLOW"**.
5. Observe real-time threat detection, Operational Risk Score (90/100 CRITICAL), WebSockets alert broadcast, and evidence snapshot generation.
6. Open **Incidents**, review the evidence snapshot, add investigation notes, and update status to **RESOLVED**.
