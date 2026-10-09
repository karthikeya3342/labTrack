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
    description: Optional[str] = "Technical Workshop conducted by student coding club."
    lab_id: Optional[int] = None
    preferred_lab_id: Optional[int] = None
    secondary_lab_id: Optional[int] = None
    expected_attendees: Optional[int] = None
    start_time: datetime
    end_time: datetime
    auto_approve: Optional[bool] = False

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
    from backend.app.core.lifecycle import reap_expired_allocations
    await reap_expired_allocations()
    query = """
        SELECT e.id, e.club_id, c.name as club_name, c.slug as club_slug, c.logo_url,
               e.lead_id, u.name as lead_name, u.roll_no as lead_roll_no,
               e.title, e.description, e.lab_id, l1.name as lab_name, l1.name as primary_lab_name,
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

@router.post("/events")
@router.post("/events/request")
async def request_club_event(
    req: ClubEventRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Club Lead or Admin submits a lab event request for approval.
    """
    user_id = int(payload["sub"])
    role = payload.get("role", "student")

    if role == "faculty":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Faculty members schedule cohort practical labs via Faculty Extra Labs."
        )

    target_lab_id = req.lab_id or req.preferred_lab_id or 1

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
    """, req.club_id, user_id, req.title, req.description, target_lab_id, req.secondary_lab_id, req.start_time, req.end_time)

    # If role is admin and auto_approve is True
    if role == "admin" and req.auto_approve:
        from datetime import timedelta
        lab_ids = [target_lab_id]
        if req.secondary_lab_id:
            lab_ids.append(req.secondary_lab_id)

        pcs = await fetch_all("""
            SELECT id, hostname, lab_id FROM pcs
            WHERE lab_id = ANY($1) AND state != 'MAINTENANCE';
        """, lab_ids)

        now = datetime.now(timezone.utc)
        is_immediate = (now >= req.start_time - timedelta(minutes=10) and now < req.end_time)
        initial_status = "HELD" if is_immediate else "PENDING"

        for pc in pcs:
            await execute("""
                UPDATE reservations
                SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP
                WHERE pc_id = $1
                  AND status IN ('PENDING', 'HELD')
                  AND time_range && tstzrange($2, $3, '[)');
            """, pc["id"], req.start_time, req.end_time)

            await execute("""
                INSERT INTO reservations (
                    student_id, pc_id, task_type, time_range, status, club_event_id, grace_deadline, notes
                ) VALUES (
                    NULL, $1, 'Practice', tstzrange($2, $3, '[)'), $4, $5, $6, $7
                );
            """, pc["id"], req.start_time, req.end_time,
                 initial_status, event_id, req.end_time, f"Club Event: {club['name']} - {req.title}")

            if is_immediate:
                await execute("""
                    UPDATE pcs
                    SET state = 'HELD', updated_at = CURRENT_TIMESTAMP
                    WHERE id = $1 AND state != 'OCCUPIED' AND state != 'MAINTENANCE';
                """, pc["id"])

        await execute("UPDATE club_events SET status = 'APPROVED', admin_notes = 'Auto-approved by Administrator' WHERE id = $1", event_id)

        return {
            "status": "success",
            "event_id": event_id,
            "approved": True,
            "message": f"Event '{req.title}' created and approved! {len(pcs)} workstations allocated for {club['name']}."
        }

    return {
        "status": "success",
        "event_id": event_id,
        "approved": False,
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

@router.post("/events/{event_id}/end")
async def end_club_event(
    event_id: int,
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Immediately ends an approved/active club event:
    - Marks event as COMPLETED
    - Marks all associated reservations as COMPLETED
    - Closes active participant sessions
    - Restores all workstations in the lab(s) back to AVAILABLE immediately
    """
    user_id = int(payload["sub"])
    role = payload.get("role", "student")

    event = await fetch_one("""
        SELECT e.id, e.title, e.club_id, e.lab_id, e.secondary_lab_id, e.status, c.name as club_name
        FROM club_events e
        JOIN clubs c ON c.id = e.club_id
        WHERE e.id = $1;
    """, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    if role != "admin" and role != "club_lead":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only club leads and administrators can conclude events."
        )

    lab_ids = [event["lab_id"]]
    if event["secondary_lab_id"]:
        lab_ids.append(event["secondary_lab_id"])

    # 1. Mark event as COMPLETED
    await execute("""
        UPDATE club_events
        SET status = 'COMPLETED'
        WHERE id = $1;
    """, event_id)

    # 2. Complete all linked reservations
    await execute("""
        UPDATE reservations
        SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
        WHERE club_event_id = $1 AND status IN ('PENDING', 'HELD', 'ACTIVE');
    """, event_id)

    # 3. Close active participant sessions
    await execute("""
        UPDATE sessions
        SET status = 'CLOSED', end_time = CURRENT_TIMESTAMP, close_reason = 'Club Event Ended by Organizer'
        WHERE club_event_id = $1 AND status = 'ACTIVE';
    """, event_id)

    # 4. Restore all workstations back to AVAILABLE
    await execute("""
        UPDATE pcs
        SET state = 'AVAILABLE', updated_at = CURRENT_TIMESTAMP
        WHERE lab_id = ANY($1) AND state != 'MAINTENANCE';
    """, lab_ids)

    return {
        "status": "success",
        "message": f"Event '{event['title']}' ended. All workstations restored to AVAILABLE for walk-in access.",
        "event_id": event_id
    }

