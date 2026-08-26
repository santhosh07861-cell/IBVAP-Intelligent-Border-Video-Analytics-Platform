from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database.connection import get_db
from database.schema import Camera, Alert, Incident, Detection, Event, ANPRResult, AuditLog
from backend.auth import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["Analytics & KPIs"])

@router.get("/kpis")
def get_kpis(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    total_cameras = db.query(Camera).count()
    cameras_online = db.query(Camera).filter(Camera.status == "ONLINE").count()
    cameras_offline = total_cameras - cameras_online

    active_alerts = db.query(Alert).filter(Alert.status.in_(["NEW", "ACKNOWLEDGED"])).count()
    critical_incidents = db.query(Incident).filter(Incident.severity == "CRITICAL", Incident.status != "RESOLVED").count()

    people_detected = db.query(Detection).filter(Detection.class_name == "person").count()
    vehicles_detected = db.query(Detection).filter(Detection.class_name.in_(["car", "truck", "bus", "motorcycle", "van"])).count()

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    intrusions_today = db.query(Event).filter(Event.timestamp >= today_start, Event.event_type.in_(["INTRUSION", "FENCE_CROSSING"])).count()

    anpr_events = db.query(ANPRResult).count()
    night_events = db.query(Event).filter(Event.event_type == "NIGHT_MOVEMENT").count()

    return {
        "cameras_total": total_cameras,
        "cameras_online": cameras_online,
        "cameras_offline": cameras_offline,
        "active_alerts": active_alerts,
        "critical_incidents": critical_incidents,
        "people_detected": people_detected,
        "vehicles_detected": vehicles_detected,
        "intrusions_today": intrusions_today,
        "anpr_events": anpr_events,
        "night_events": night_events
    }

@router.get("/charts")
def get_chart_data(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    # Hourly event trends over the past 24 hours
    now = datetime.utcnow()
    hours_data = []
    for i in range(12, -1, -1):
        h_start = now - timedelta(hours=i+1)
        h_end = now - timedelta(hours=i)
        cnt = db.query(Event).filter(Event.timestamp >= h_start, Event.timestamp < h_end).count()
        hours_data.append({
            "time": h_start.strftime("%H:00"),
            "events": cnt
        })

    # Severity distribution
    sev_counts = db.query(Alert.severity, func.count(Alert.id)).group_by(Alert.severity).all()
    sev_map = {s: c for s, c in sev_counts}

    return {
        "event_trends": hours_data,
        "severity_distribution": [
            {"name": "CRITICAL", "value": sev_map.get("CRITICAL", 0), "color": "#ef4444"},
            {"name": "HIGH", "value": sev_map.get("HIGH", 0), "color": "#f97316"},
            {"name": "MEDIUM", "value": sev_map.get("MEDIUM", 0), "color": "#eab308"},
            {"name": "LOW", "value": sev_map.get("LOW", 0), "color": "#3b82f6"},
            {"name": "INFO", "value": sev_map.get("INFO", 0), "color": "#10b981"}
        ]
    }
