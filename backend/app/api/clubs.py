from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from backend.app.core.security import get_current_user_token_payload
from backend.app.core.database import fetch_all, fetch_one, execute, fetch_val

router = APIRouter(prefix="/clubs", tags=["Technical Coding Clubs"])

class ClubEventRequest(BaseModel):
    club_id: int
    title: str
    description: Optional[str] = None
    lab_id: int
    secondary_lab_id: Optional[int] = None
    start_time: datetime
    end_time: datetime

@router.get("")
async def get_all_clubs():
    """Returns the 5 official technical coding clubs."""
    clubs = await fetch_all("""
        SELECT id, name, slug, logo_url, description, created_at
        FROM clubs
        ORDER BY id ASC;
    """)
    return clubs

@router.get("/events")
async def list_club_events(status_filter: Optional[str] = None):
    """Lists all club events with status and lab allocation."""
    query = """
        SELECT e.id, e.club_id, c.name as club_name, c.slug as club_slug, c.logo_url,
               e.lead_id, u.name as lead_name, u.roll_no as lead_roll_no,
               e.title, e.description, e.lab_id, l1.name as lab_name,
               e.secondary_lab_id, l2.name as secondary_lab_name,
               lower(e.time_range) as start_time,
               upper(e.time_range) as end_time,
               e.status, e.admin_notes, e.created_at
        FROM club_events e
        JOIN clubs c ON c.id = e.club_id
        LEFT JOIN users u ON u.id = e.lead_id
        LEFT JOIN labs l1 ON l1.id = e.lab_id
        LEFT JOIN labs l2 ON l2.id = e.secondary_lab_id
    """
    params = []
    if status_filter:
        query += " WHERE e.status = $1"
        params.append(status_filter)
    query += " ORDER BY e.created_at DESC;"

    events = await fetch_all(query, *params)
    return events

@router.post("/events/request")
async def request_club_event(
    req: ClubEventRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Club Lead submits a lab event request for approval.
    """
    user_id = int(payload["sub"])
    role = payload.get("role", "student")

    if req.start_time >= req.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start time must precede end time."
        )

    # Verify club exists
    club = await fetch_one("SELECT id, name FROM clubs WHERE id = $1", req.club_id)
    if not club:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technical club not found.")

    # Insert pending event
    event_id = await fetch_val("""
        INSERT INTO club_events (
            club_id, lead_id, title, description, lab_id, secondary_lab_id, time_range, status
        ) VALUES (
            $1, $2, $3, $4, $5, $6, tstzrange($7, $8, '[)'), 'PENDING'
        ) RETURNING id;
    """, req.club_id, user_id, req.title, req.description, req.lab_id, req.secondary_lab_id, req.start_time, req.end_time)

    return {
        "status": "success",
        "event_id": event_id,
        "message": f"Event '{req.title}' requested for {club['name']}. Awaiting Admin Approval."
    }

@router.get("/events/{event_id}/roster")
async def get_event_attendance_roster(event_id: int):
    """
    Live attendance and participation roster for a club event:
    Shows which students are active, their workstations, check-in time, and duration.
    Visible to both Admin and Club Leads.
    """
    event = await fetch_one("""
        SELECT e.id, e.title, c.name as club_name, c.logo_url,
               lower(e.time_range) as start_time, upper(e.time_range) as end_time,
               e.status, l.name as lab_name
        FROM club_events e
        JOIN clubs c ON c.id = e.club_id
        LEFT JOIN labs l ON l.id = e.lab_id
        WHERE e.id = $1;
    """, event_id)

    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Club event not found.")

    # Fetch active and past participant sessions
    attendees = await fetch_all("""
        SELECT s.id as session_id, u.roll_no, u.name as student_name,
               p.hostname, s.start_time as checkin_time, s.end_time,
               s.status as session_status,
               ROUND(EXTRACT(EPOCH FROM (COALESCE(s.end_time, CURRENT_TIMESTAMP) - s.start_time)) / 60.0, 1) as duration_minutes
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        JOIN pcs p ON p.id = s.pc_id
        WHERE s.club_event_id = $1
        ORDER BY s.start_time DESC;
    """, event_id)

    total_attendees = len(attendees)
    active_now = sum(1 for a in attendees if a["session_status"] == "ACTIVE")

    return {
        "event": event,
        "metrics": {
            "total_attendees": total_attendees,
            "active_now": active_now
        },
        "roster": attendees
    }
