from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database.connection import get_db
from database.schema import Camera, Alert, Incident, Detection, Event, ANPRResult, AuditLog
from backend.stream_manager import stream_manager
from backend.auth import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["Analytics & KPIs"])

@router.get("/kpis")
def get_kpis(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    total_cameras = db.query(Camera).count()
    cameras_online = db.query(Camera).filter(Camera.status == "ONLINE").count()
    cameras_offline = total_cameras - cameras_online

    active_alerts = db.query(Alert).filter(Alert.status.in_(["NEW", "ACTIVE"])).count()
    critical_incidents = db.query(Incident).filter(Incident.severity == "CRITICAL", Incident.status.in_(["NEW", "ACTIVE", "INVESTIGATING", "OPEN"])).count()

    people_detected = stream_manager.get_active_confirmed_people_count()
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
    # Hourly event trends over the past 24 hours (24 1-hour buckets)
    now = datetime.utcnow()
    hours_data = []
    total_events_24h = 0
    
    for i in range(23, -1, -1):
        h_start = now - timedelta(hours=i+1)
        h_end = now - timedelta(hours=i)
        # Count actual events in this 1-hour window
        cnt = db.query(Event).filter(Event.timestamp >= h_start, Event.timestamp < h_end).count()
        total_events_24h += cnt
        hours_data.append({
            "time": h_end.strftime("%H:00"),
            "events": cnt
        })

    # Real severity distribution from actual Alert records
    sev_counts = db.query(Alert.severity, func.count(Alert.id)).group_by(Alert.severity).all()
    sev_map = {str(s).upper(): int(c) for s, c in sev_counts if s is not None}
    total_alerts = sum(sev_map.values())

    severity_distribution = [
        {"name": "CRITICAL", "value": sev_map.get("CRITICAL", 0), "color": "#ef4444"},
        {"name": "HIGH", "value": sev_map.get("HIGH", 0), "color": "#f97316"},
        {"name": "MEDIUM", "value": sev_map.get("MEDIUM", 0), "color": "#eab308"},
        {"name": "LOW", "value": sev_map.get("LOW", 0), "color": "#3b82f6"},
        {"name": "INFO", "value": sev_map.get("INFO", 0), "color": "#10b981"}
    ]

    # Real detection distribution by object class
    class_counts = db.query(Detection.class_name, func.count(Detection.id)).group_by(Detection.class_name).all()
    class_distribution = [{"name": str(cn).upper(), "count": int(c)} for cn, c in class_counts if cn is not None]

    return {
        "total_events_24h": total_events_24h,
        "total_alerts": total_alerts,
        "event_trends": hours_data,
        "severity_distribution": severity_distribution,
        "class_distribution": class_distribution
    }

