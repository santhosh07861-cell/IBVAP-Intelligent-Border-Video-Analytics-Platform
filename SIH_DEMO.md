# SIH 2026 Evaluation & Demonstration Guide

This guide walks evaluators step-by-step through testing IBVAP.

---

## 1. Start System

- **Backend**: `uvicorn backend.main:app --port 8000`
- **Frontend**: `npm run dev` in `frontend/`

---

## 2. SIH Workflow Verification

```text
Login -> Select MP4 Demo Video -> Observe Bounding Boxes & Tracks -> Draw Virtual Fence Zone -> Trigger Intrusion -> Verify Alert broadcasted via WebSocket -> Open Incident details -> Inspect Snapshot & Video clip evidence -> Add note & Resolve -> Check updated Analytics charts.
```

1. **Authentication**: Open `http://localhost:5173`. Click the **Administrator** quick-login button and log in.
2. **Command Center**: View real-time KPI counters (`Cameras Online`, `Active Alerts`, `Critical Incidents`, `People Detected`).
3. **Surveillance Grid**: Click **Live Surveillance** to test 1x1, 2x2, and 3x3 camera layouts with live AI bounding box overlays.
4. **Trigger Intrusion**: Go to **SIH Demo Center** (`/demo`) and click **"TRIGGER SIH INTRUSION WORKFLOW"**.
5. **Incident Handling**: Navigate to **Incidents**, select the generated incident, inspect the snapshot evidence, write an investigation note, and update status to **RESOLVED**.
6. **Analytics & ANPR**: Check **ANPR License Plates** for OCR logs and **Border Analytics** for hourly trend charts.
