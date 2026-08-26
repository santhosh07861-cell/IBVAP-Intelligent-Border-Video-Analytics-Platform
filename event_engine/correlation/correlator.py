import time
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from database.schema import Incident, Alert, Event, Evidence
from event_engine.risk.scorer import OperationalRiskScorer

logger = logging.getLogger(__name__)

class EventCorrelator:
    def __init__(self, cooldown_seconds: int = 25):
        self.cooldown_seconds = cooldown_seconds
        self.last_incident_time: Dict[str, datetime] = {}
        self.active_incidents: Dict[str, str] = {}  # key: camera_id_track_id -> incident_id
        self.scorer = OperationalRiskScorer()

    def process_event(self, db: Session, event_data: dict, evidence_path: str = None) -> Optional[Incident]:
        """
        Deduplicates incoming raw events and correlates related observations
        (person + night + restricted zone + loitering) into unified Incidents.
        """
        camera_id = event_data.get("camera_id")
        track_id = event_data.get("track_id", 0)
        event_type = event_data.get("event_type", "INTRUSION")
        conditions = event_data.get("conditions", {})

        key = f"{camera_id}_{track_id}"
        now = datetime.utcnow()

        # Check deduplication / cooldown
        if key in self.last_incident_time:
            time_diff = (now - self.last_incident_time[key]).total_seconds()
            if time_diff < self.cooldown_seconds:
                # Existing incident still active, append event to existing incident
                existing_id = self.active_incidents.get(key)
                if existing_id:
                    inc = db.query(Incident).filter(Incident.id == existing_id).first()
                    if inc:
                        related_ids = list(inc.related_event_ids or [])
                        ev_id = event_data.get("event_id", str(uuid.uuid4()))
                        related_ids.append(ev_id)
                        inc.related_event_ids = related_ids
                        db.commit()
                        return inc

        # Compute Operational Risk Score
        risk_result = self.scorer.calculate_score(conditions)
        risk_score = risk_result["risk_score"]
        severity = risk_result["severity"]

        # Generate unique incident number (e.g. INC-20260823-8912)
        inc_number = f"INC-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"

        title = f"{severity} Intrusion Alert - Camera {camera_id}"
        desc = f"Correlated event '{event_type}' detected object track #{track_id}. Risk Score: {risk_score}/100. Active factors: {', '.join([k for k, v in conditions.items() if v])}."

        incident = Incident(
            id=str(uuid.uuid4()),
            incident_number=inc_number,
            camera_id=camera_id,
            title=title,
            description=desc,
            severity=severity,
            risk_score=risk_score,
            status="NEW",
            related_event_ids=[event_data.get("event_id", str(uuid.uuid4()))],
            start_time=now
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)

        # Create Alert
        alert = Alert(
            id=str(uuid.uuid4()),
            incident_id=incident.id,
            camera_id=camera_id,
            event_type=event_type,
            severity=severity,
            risk_score=risk_score,
            confidence=event_data.get("confidence", 0.90),
            status="NEW",
            evidence_url=evidence_path,
            timestamp=now
        )
        db.add(alert)

        # Create Evidence record if snapshot path provided
        if evidence_path:
            ev_record = Evidence(
                id=str(uuid.uuid4()),
                incident_id=incident.id,
                camera_id=camera_id,
                evidence_type="snapshot",
                file_path=evidence_path,
                file_url=f"/static/evidence/{evidence_path.split('/')[-1]}",
                metadata_json={"risk_score": risk_score, "conditions": conditions}
            )
            db.add(ev_record)

        db.commit()

        self.last_incident_time[key] = now
        self.active_incidents[key] = incident.id

        return incident
