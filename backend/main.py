import os
import time
import json
import uuid
import asyncio
import logging
from datetime import datetime
from typing import List, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database.connection import engine, Base, SessionLocal, get_db
from database.schema import (
    Role, User, Camera, CameraHealth, CameraZone, ZoneRule,
    ModelRegistry, AuditLog, Event, Alert
)
from backend.auth import get_password_hash
from backend.routers import (
    auth_router, camera_router, zone_router, alert_router,
    incident_router, anpr_router, face_router, analytics_router,
    health_router, model_router, audit_router, demo_router,
    evidence_router
)
from ai_engine.tracking.tracker import MultiObjectTracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize DB tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="IBVAP - Intelligent Border Video Analytics Platform",
    description="AI-Based Intelligent Video Analytics Platform for Border Surveillance (SIH 2026)",
    version="1.0.0"
)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve evidence static files
os.makedirs("storage/evidence/snapshots", exist_ok=True)
os.makedirs("storage/evidence/face/snapshots", exist_ok=True)
os.makedirs("storage/evidence/face/crops", exist_ok=True)
os.makedirs("storage/evidence/face/watchlist", exist_ok=True)
app.mount("/static/evidence", StaticFiles(directory="storage/evidence/snapshots"), name="evidence")
app.mount("/static/face", StaticFiles(directory="storage/evidence/face"), name="face_static")

from fastapi.responses import RedirectResponse, HTMLResponse

@app.get("/", response_class=HTMLResponse)
def root_index():
    return """
    <!DOCTYPE html>
    <html>
      <head>
        <title>IBVAP - Intelligent Border Video Analytics Platform</title>
        <style>
          body { background: #0a0d14; color: #f8fafc; font-family: monospace; padding: 40px; text-align: center; }
          .card { background: #111622; border: 1px solid #252d42; border-radius: 12px; padding: 30px; max-width: 600px; margin: 0 auto; }
          h1 { color: #3b82f6; }
          a.btn { display: inline-block; background: #2563eb; color: #fff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; margin: 10px; }
          a.btn-sec { background: #1e293b; border: 1px solid #334155; color: #94a3b8; }
        </style>
      </head>
      <body>
        <div class="card">
          <h1>IBVAP COMMAND SYSTEM</h1>
          <p>SIH 2026 Intelligent Border Video Analytics Platform</p>
          <p>Backend API Engine is <b>ONLINE</b>.</p>
          <div style="margin-top: 25px;">
            <a href="http://localhost:5173" class="btn">OPEN REACT DASHBOARD (Port 5173) &rarr;</a>
            <br>
            <a href="/docs" class="btn btn-sec">VIEW API SWAGGER DOCS (/docs)</a>
          </div>
        </div>
      </body>
    </html>
    """

# Include Routers
app.include_router(auth_router.router)
app.include_router(camera_router.router)
app.include_router(zone_router.router)
app.include_router(alert_router.router)
app.include_router(incident_router.router)
app.include_router(anpr_router.router)
app.include_router(face_router.router)
app.include_router(analytics_router.router)
app.include_router(health_router.router)
app.include_router(model_router.router)
app.include_router(audit_router.router)
app.include_router(demo_router.router)
app.include_router(evidence_router.router)
app.include_router(evidence_router.detections_router)

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("WebSocket client disconnected.")

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keepalive / listen for client ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.on_event("startup")
async def startup_event():
    from backend.stream_manager import stream_manager
    stream_manager.set_loop(asyncio.get_running_loop())
    seed_database()

def seed_database():
    db = SessionLocal()
    try:
        # Seed Roles
        roles_data = [
            ("Administrator", "Full system configuration & administrative access"),
            ("Security Operator", "Real-time monitoring, alert acknowledgement, incident handling"),
            ("Analyst", "Event analytics, ANPR search & report generation"),
            ("Viewer", "Read-only surveillance view")
        ]
        role_map = {}
        for rname, rdesc in roles_data:
            r = db.query(Role).filter(Role.name == rname).first()
            if not r:
                r = Role(id=str(uuid.uuid4()), name=rname, description=rdesc)
                db.add(r)
                db.commit()
                db.refresh(r)
            role_map[rname] = r

        # Seed Users
        users_data = [
            ("admin", "admin@ibvap.gov.in", "Admin Pass123!", "Commandant R. S. Rathore", "Administrator"),
            ("operator", "operator@ibvap.gov.in", "Operator Pass123!", "Inspector Vikram Singh", "Security Operator"),
            ("analyst", "analyst@ibvap.gov.in", "Analyst Pass123!", "Sub-Inspector Anita Sharma", "Analyst"),
            ("viewer", "viewer@ibvap.gov.in", "Viewer Pass123!", "Observer Guard", "Viewer")
        ]
        for uname, email, plain_pwd, fname, rname in users_data:
            u = db.query(User).filter(User.username == uname).first()
            if not u:
                u = User(
                    id=str(uuid.uuid4()),
                    username=uname,
                    email=email,
                    hashed_password=get_password_hash(plain_pwd),
                    full_name=fname,
                    role_id=role_map[rname].id,
                    is_active=True
                )
                db.add(u)
        db.commit()

        # Seed AI Model Registry
        m = db.query(ModelRegistry).filter(ModelRegistry.model_name == "YOLOv8n Border Surveillance").first()
        if not m:
            m = ModelRegistry(
                id=str(uuid.uuid4()),
                model_name="YOLOv8n Border Surveillance",
                model_type="detector",
                version="v1.4.2",
                framework="OpenCV DNN / PyTorch",
                file_path="storage/models/yolov8n.onnx",
                metrics={"mAP_50": 0.892, "precision": 0.914, "recall": 0.876, "inference_fps": 64.2},
                is_active=True
            )
            db.add(m)
            db.commit()

    except Exception as e:
        logger.error(f"Error seeding database: {e}")
    finally:
        db.close()
