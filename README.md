# IBVAP — Intelligent Border Video Analytics Platform

**SIH 2026 Problem Statement:** AI-Based Intelligent Video Analytics Platform for Border Surveillance using Existing CCTV Infrastructure.

IBVAP transforms standard IP-based CCTV cameras into an intelligent AI-powered border surveillance network without requiring dedicated smart-camera hardware.

---

## Key Features

- **Multi-Source Ingestion**: Primary Uploaded MP4 demo playback, local Webcam, and RTSP stream ingestion with automatic reconnect, exponential backoff, and latency monitoring.
- **Dual AI Inference Engine**: Real YOLO (OpenCV DNN / PyTorch with automatic CUDA/CPU detection) + deterministic Fallback Demo Adapter.
- **Multi-Object Tracking**: Centroid / ByteTrack tracking maintaining track IDs, trajectories, entry/exit time, and dwell duration.
- **Virtual Fencing & Intrusion Detection**: Interactive visual polygon and line-crossing fence editor with real-time containment checking.
- **Transparent Operational Risk Score**: Configurable 0–100 scoring based on active threat factors (Night Mode + Restricted Zone + Fence Crossing + Loitering).
- **Incident Correlation & Evidence Capture**: Correlates related observations into unified Incidents, capturing full-frame snapshots, cropped objects/plates, and video clips.
- **Real-Time WebSockets**: Live telemetry streaming to dynamic React Command Center without page refresh.
- **ANPR & Face Detection**: License plate OCR text extraction and face bounding box detection.
- **Role-Based Access Control (RBAC)**: JWT authentication with 4 roles (Administrator, Security Operator, Analyst, Viewer).

---

## Quick Start (Local Run)

### 1. Backend Setup

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start FastAPI backend
PYTHONPATH=. uvicorn backend.main:app --reload --port 8000
```

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open your browser at `http://localhost:5173`.

---

## Demo Credentials (SIH Evaluation)

| Role | Username | Password |
|---|---|---|
| **Administrator** | `admin` | `Admin Pass123!` |
| **Security Operator** | `operator` | `Operator Pass123!` |
| **Analyst** | `analyst` | `Analyst Pass123!` |
| **Viewer** | `viewer` | `Viewer Pass123!` |

---

## SIH 2026 Demo Execution

1. Log in with `admin` credentials.
2. Navigate to **SIH Demo Center** (`/demo`).
3. Click **"TRIGGER SIH INTRUSION WORKFLOW"**.
4. Observe real-time WebSockets alert broadcast, risk score calculation (90/100 CRITICAL), evidence snapshot capture, and incident creation.
5. Open the created Incident details to review snapshot evidence, add operator investigation notes, and resolve the incident.
