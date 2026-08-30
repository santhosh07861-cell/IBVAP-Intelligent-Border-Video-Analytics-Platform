import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.connection import get_db
from database.schema import Incident, IncidentNote, Evidence, AuditLog
from backend.auth import get_current_user, RequireRole

router = APIRouter(prefix="/api/incidents", tags=["Incident Management"])

class StatusUpdate(BaseModel):
    status: str  # ACKNOWLEDGED, INVESTIGATING, RESOLVED, FALSE_POSITIVE

class NoteCreate(BaseModel):
    note_text: str

@router.get("")
def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(Incident)
    if status:
        query = query.filter(Incident.status == status)
    if severity:
        query = query.filter(Incident.severity == severity)

    incidents = query.order_by(Incident.created_at.desc()).limit(limit).all()
    res = []
    for inc in incidents:
        cam = db.query(Camera).filter((Camera.id == inc.camera_id) | (Camera.camera_id == inc.camera_id)).first()
        cam_display = f"{cam.camera_id} - {cam.name}" if cam else inc.camera_id
        ev_count = db.query(Evidence).filter(Evidence.incident_id == inc.id).count()
        notes_count = db.query(IncidentNote).filter(IncidentNote.incident_id == inc.id).count()
        res.append({
            "id": inc.id,
            "incident_number": inc.incident_number,
            "camera_id": inc.camera_id,
            "camera_name": cam.name if cam else "Camera",
            "camera_number": cam.camera_id if cam else inc.camera_id,
            "camera_display": cam_display,
            "title": inc.title,
            "description": inc.description,
            "severity": inc.severity,
            "risk_score": inc.risk_score,
            "status": inc.status,
            "start_time": f"{inc.start_time.isoformat()}Z" if inc.start_time else None,
            "created_at": f"{inc.created_at.isoformat()}Z" if inc.created_at else None,
            "evidence_count": ev_count,
            "notes_count": notes_count
        })
    return res

@router.get("/{incident_id}")
def get_incident_detail(incident_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    inc = db.query(Incident).filter((Incident.id == incident_id) | (Incident.incident_number == incident_id)).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    notes = db.query(IncidentNote).filter(IncidentNote.incident_id == inc.id).order_by(IncidentNote.created_at.asc()).all()
    evidences = db.query(Evidence).filter(Evidence.incident_id == inc.id).all()

    return {
        "id": inc.id,
        "incident_number": inc.incident_number,
        "camera_id": inc.camera_id,
        "title": inc.title,
        "description": inc.description,
        "severity": inc.severity,
        "risk_score": inc.risk_score,
        "status": inc.status,
        "related_event_ids": inc.related_event_ids,
        "start_time": inc.start_time,
        "end_time": inc.end_time,
        "created_at": inc.created_at,
        "notes": [
            {
                "id": n.id,
                "author_name": n.author_name,
                "note_text": n.note_text,
                "created_at": n.created_at
            } for n in notes
        ],
        "evidence": [
            {
                "id": e.id,
                "evidence_type": e.evidence_type,
                "file_url": e.file_url,
                "created_at": e.created_at,
                "metadata": e.metadata_json
            } for e in evidences
        ]
    }

@router.put("/{incident_id}/status", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def update_incident_status(incident_id: str, payload: StatusUpdate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    inc = db.query(Incident).filter((Incident.id == incident_id) | (Incident.incident_number == incident_id)).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    inc.status = payload.status
    if payload.status in ["RESOLVED", "FALSE_POSITIVE"]:
        inc.end_time = datetime.utcnow()

    db.commit()

    audit = AuditLog(
        username=current_user.username,
        action="UPDATE_INCIDENT_STATUS",
        resource="incidents",
        details={"incident_id": inc.incident_number, "new_status": payload.status}
    )
    db.add(audit)
    db.commit()

    return {"status": "success", "incident_id": inc.id, "new_status": inc.status}

@router.post("/{incident_id}/notes", dependencies=[Depends(RequireRole(["Administrator", "Security Operator", "Analyst"]))])
def add_incident_note(incident_id: str, payload: NoteCreate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    inc = db.query(Incident).filter((Incident.id == incident_id) | (Incident.incident_number == incident_id)).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    note = IncidentNote(
        id=str(uuid.uuid4()),
        incident_id=inc.id,
        user_id=current_user.id,
        author_name=current_user.full_name or current_user.username,
        note_text=payload.note_text
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    return {"status": "success", "note_id": note.id, "author_name": note.author_name, "note_text": note.note_text, "created_at": note.created_at}


class BulkDeleteIncidentRequest(BaseModel):
    incident_ids: List[str]


@router.delete("/{incident_id}", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def delete_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Permanently deletes a security incident record from the database.
    Creates an immutable audit log entry.
    """
    inc = db.query(Incident).filter((Incident.id == incident_id) | (Incident.incident_number == incident_id)).first()
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident #{incident_id} not found")

    target_id = inc.id
    inc_num = inc.incident_number
    cam_id = inc.camera_id
    title = inc.title
    sev = inc.severity

    # Record audit log
    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="DELETE_INCIDENT",
        resource="incidents",
        details={
            "incident_id": target_id,
            "incident_number": inc_num,
            "camera_id": cam_id,
            "title": title,
            "severity": sev
        }
    )
    db.add(audit)

    # Disassociate evidence so snapshots are preserved in gallery
    db.query(Evidence).filter(Evidence.incident_id == target_id).update({Evidence.incident_id: None}, synchronize_session=False)

    # Delete notes
    db.query(IncidentNote).filter(IncidentNote.incident_id == target_id).delete(synchronize_session=False)

    # Delete incident
    db.delete(inc)
    db.commit()

    return {
        "success": True,
        "message": f"Incident {inc_num} deleted successfully",
        "deleted_id": target_id
    }


@router.post("/bulk-delete", dependencies=[Depends(RequireRole(["Administrator", "Security Operator"]))])
def bulk_delete_incidents(
    payload: BulkDeleteIncidentRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Permanently bulk-deletes multiple security incident records from the database.
    """
    if not payload.incident_ids:
        raise HTTPException(status_code=400, detail="No incident IDs provided for deletion")

    if len(payload.incident_ids) > 100:
        raise HTTPException(status_code=400, detail="Cannot delete more than 100 incidents at once")

    items = db.query(Incident).filter(
        (Incident.id.in_(payload.incident_ids)) | (Incident.incident_number.in_(payload.incident_ids))
    ).all()
    if not items:
        return {"success": True, "deleted_count": 0, "deleted_ids": [], "message": "No matching incidents found"}

    deleted_ids = []
    for item in items:
        deleted_ids.append(item.id)
        # Disassociate evidence
        db.query(Evidence).filter(Evidence.incident_id == item.id).update({Evidence.incident_id: None}, synchronize_session=False)
        db.query(IncidentNote).filter(IncidentNote.incident_id == item.id).delete(synchronize_session=False)
        db.delete(item)

    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        username=current_user.username if current_user else "operator",
        action="BULK_DELETE_INCIDENTS",
        resource="incidents",
        details={
            "deleted_count": len(deleted_ids),
            "deleted_ids": deleted_ids
        }
    )
    db.add(audit)
    db.commit()

    return {
        "success": True,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "message": f"Successfully deleted {len(deleted_ids)} incident records"
    }

