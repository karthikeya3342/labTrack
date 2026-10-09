from fastapi import APIRouter, HTTPException, status, Depends
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from backend.app.core.security import get_current_user_token_payload
from backend.app.core.database import fetch_all, fetch_one, execute, fetch_val
from backend.app.core.lifecycle import reap_expired_allocations

router = APIRouter(prefix="/admin", tags=["Admin Operations"])

class MaintenanceToggleRequest(BaseModel):
    is_maintenance: bool
    reason: Optional[str] = "Hardware diagnostics"

class PolicyUpdateRequest(BaseModel):
    policy: str  # 'FCFS', 'PRIORITY_AGING', 'INTELLIGENT_GA'

CURRENT_POLICY = {"active_policy": "INTELLIGENT_GA"}

def verify_admin(payload: dict):
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required"
        )

@router.post("/pcs/{hostname}/maintenance")
async def toggle_pc_maintenance(
    hostname: str,
    req: MaintenanceToggleRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    verify_admin(payload)
    pc = await fetch_one("SELECT id, state FROM pcs WHERE hostname = $1", hostname)
    if not pc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"PC {hostname} not found")

    new_state = "MAINTENANCE" if req.is_maintenance else "AVAILABLE"
    await execute(
        "UPDATE pcs SET state = $1, maintenance_reason = $2 WHERE id = $3",
        new_state, req.reason if req.is_maintenance else None, pc["id"]
    )
    return {"hostname": hostname, "state": new_state, "reason": req.reason}

@router.post("/sessions/{session_id}/force-release")
async def force_release_session(
    session_id: int,
    payload: dict = Depends(get_current_user_token_payload)
):
    verify_admin(payload)
    sess_info = await fetch_one("SELECT pc_id FROM sessions WHERE id = $1", session_id)
    success = await fetch_val(
        "SELECT fn_close_session($1, $2);",
        session_id,
        "Force released by Administrator"
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found or already closed")

    promotion = None
    if sess_info:
        pc = await fetch_one("SELECT id, lab_id FROM pcs WHERE id = $1", sess_info["pc_id"])
        if pc:
            from backend.app.api.scheduler import promote_next_taskpool_entry
            promotion = await promote_next_taskpool_entry(pc["id"], pc["lab_id"])

    return {"status": "force_released", "session_id": session_id, "promoted_waitlist_entry": promotion}

@router.get("/licenses")
async def get_license_tracker():
    licenses = await fetch_all("""
        SELECT s.id, s.name, s.category, s.requires_gpu,
               l.active_seats, l.max_seats,
               ROUND((l.active_seats::numeric / GREATEST(1, l.max_seats)::numeric) * 100, 1) as utilization_pct
        FROM software s
        JOIN licenses l ON l.software_id = s.id
        ORDER BY s.id
    """)
    return licenses

@router.get("/policy")
async def get_active_policy():
    return CURRENT_POLICY

@router.post("/policy")
async def update_active_policy(
    req: PolicyUpdateRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    verify_admin(payload)
    if req.policy not in ("FCFS", "PRIORITY_AGING", "INTELLIGENT_GA"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid policy type")
    CURRENT_POLICY["active_policy"] = req.policy
    return CURRENT_POLICY

@router.get("/telemetry-summary")
async def get_telemetry_summary():
    """
    Returns real-time aggregated CPU and RAM utilization metrics across all labs
    for administrative monitoring and anomaly detection.
    """
    await reap_expired_allocations()
    summary = await fetch_one("""
        WITH latest_samples AS (
            SELECT DISTINCT ON (pc_id)
                   pc_id, cpu_percent, memory_percent, memory_rss_bytes, load_average, recorded_at
            FROM telemetry_samples
            WHERE recorded_at >= CURRENT_TIMESTAMP - INTERVAL '1 hour'
            ORDER BY pc_id, recorded_at DESC
        )
        SELECT
            (SELECT COUNT(*) FROM pcs WHERE state = 'OCCUPIED') as occupied_pcs,
            (SELECT COUNT(*) FROM pcs WHERE state = 'AVAILABLE') as available_pcs,
            (SELECT COUNT(*) FROM pcs WHERE state = 'HELD') as held_pcs,
            COUNT(ls.pc_id) as reporting_pcs,
            COALESCE(ROUND(AVG(ls.cpu_percent)::numeric, 1), 0.0) as avg_cpu_percent,
            COALESCE(ROUND(AVG(ls.memory_percent)::numeric, 1), 0.0) as avg_memory_percent,
            COALESCE(ROUND(SUM(ls.memory_rss_bytes / 1048576.0)::numeric, 1), 0.0) as total_ram_used_mb,
            COUNT(ls.pc_id) FILTER (WHERE ls.cpu_percent >= 80.0 OR ls.memory_percent >= 85.0) as high_load_pcs
        FROM latest_samples ls;
    """)

    pc_metrics = await fetch_all("""
        SELECT p.id, p.hostname, p.state, l.name as lab_name,
               ts.cpu_percent, ts.memory_percent,
               ROUND((ts.memory_rss_bytes / 1048576.0)::numeric, 1) as memory_rss_mb,
               ts.load_average, ts.process_count, ts.recorded_at
        FROM pcs p
        JOIN labs l ON l.id = p.lab_id
        LEFT JOIN LATERAL (
            SELECT cpu_percent, memory_percent, memory_rss_bytes, load_average, process_count, recorded_at
            FROM telemetry_samples
            WHERE pc_id = p.id
            ORDER BY recorded_at DESC
            LIMIT 1
        ) ts ON TRUE
        ORDER BY p.hostname ASC;
    """)

    return {
        "summary": summary,
        "workstations": pc_metrics
    }

class UserRoleUpdateRequest(BaseModel):
    role: str  # 'faculty', 'student', 'club_lead', 'admin'

class EventApprovalRequest(BaseModel):
    admin_notes: Optional[str] = "Approved by Lab Administrator"

@router.get("/users")
async def list_users(payload: dict = Depends(get_current_user_token_payload)):
    verify_admin(payload)
    users = await fetch_all("""
        SELECT id, roll_no, name, email, role, is_active, created_at
        FROM users
        ORDER BY id ASC;
    """)
    return users

@router.post("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    req: UserRoleUpdateRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    verify_admin(payload)
    if req.role not in ("faculty", "student", "club_lead", "admin"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role specified")
    
    user = await fetch_one("SELECT id, name, roll_no FROM users WHERE id = $1", user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await execute("UPDATE users SET role = $1 WHERE id = $2", req.role, user_id)
    return {
        "status": "success",
        "user_id": user_id,
        "name": user["name"],
        "roll_no": user["roll_no"],
        "new_role": req.role,
        "message": f"User {user['name']} ({user['roll_no']}) updated to role '{req.role}'"
    }

@router.post("/clubs/events/{event_id}/approve")
@router.post("/club-events/{event_id}/approve")
async def approve_club_event(
    event_id: int,
    req: EventApprovalRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    verify_admin(payload)
    event = await fetch_one("""
        SELECT e.id, e.title, e.club_id, e.lab_id, e.secondary_lab_id,
               lower(e.time_range) as start_time, upper(e.time_range) as end_time,
               e.status, c.name as club_name
        FROM club_events e
        JOIN clubs c ON c.id = e.club_id
        WHERE e.id = $1;
    """, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if event["status"] != "PENDING":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Event is already {event['status']}")

    # Allocate all PCs in assigned lab(s)
    lab_ids = [event["lab_id"]]
    if event["secondary_lab_id"]:
        lab_ids.append(event["secondary_lab_id"])

    pcs = await fetch_all("""
        SELECT id, hostname, lab_id FROM pcs
        WHERE lab_id = ANY($1) AND state != 'MAINTENANCE';
    """, lab_ids)

    now = datetime.now(timezone.utc)
    # Only flip to HELD if within 10 minutes of start time; future events stay PENDING and workstations stay AVAILABLE
    is_immediate = (now >= event["start_time"] - timedelta(minutes=10) and now < event["end_time"])
    initial_status = "HELD" if is_immediate else "PENDING"

    admin_id = int(payload["sub"])
    for pc in pcs:
        await execute("""
            UPDATE reservations
            SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP
            WHERE pc_id = $1
              AND status IN ('PENDING', 'HELD')
              AND time_range && tstzrange($2, $3, '[)');
        """, pc["id"], event["start_time"], event["end_time"])

        await execute("""
            INSERT INTO reservations (
                student_id, pc_id, task_type, time_range, status, club_event_id, grace_deadline, notes
            ) VALUES (
                NULL, $1, 'Practice', tstzrange($2, $3, '[)'), $4, $5, $6, $7
            );
        """, pc["id"], event["start_time"], event["end_time"],
             initial_status, event_id, event["end_time"], f"Club Event: {event['club_name']} - {event['title']}")

        if is_immediate:
            # Set workstation to HELD unless an active student session is currently occupying it
            await execute("""
                UPDATE pcs
                SET state = 'HELD', updated_at = CURRENT_TIMESTAMP
                WHERE id = $1 AND state != 'OCCUPIED' AND state != 'MAINTENANCE';
            """, pc["id"])

    await execute("""
        UPDATE club_events
        SET status = 'APPROVED', admin_notes = $1
        WHERE id = $2;
    """, req.admin_notes, event_id)

    return {
        "status": "approved",
        "event_id": event_id,
        "title": event["title"],
        "allocated_workstations_count": len(pcs),
        "message": f"Event approved! {len(pcs)} workstations reserved for {event['club_name']}."
    }

@router.post("/clubs/events/{event_id}/reject")
async def reject_club_event(
    event_id: int,
    req: EventApprovalRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    verify_admin(payload)
    event = await fetch_one("SELECT id, status FROM club_events WHERE id = $1", event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    await execute("UPDATE club_events SET status = 'REJECTED', admin_notes = $1 WHERE id = $2", req.admin_notes, event_id)
    return {"status": "rejected", "event_id": event_id, "reason": req.admin_notes}

@router.post("/system/release-all")
async def release_all_system_holds(
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Master Reset: Immediately releases all holds, closes active sessions,
    marks all reservations and club events completed, and returns all
    workstations to AVAILABLE normal walk-in kiosk mode.
    """
    verify_admin(payload)

    # 1. Complete all active/pending/held reservations
    await execute("""
        UPDATE reservations
        SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('PENDING', 'HELD', 'ACTIVE');
    """)

    # 2. Complete all approved/pending club events
    await execute("""
        UPDATE club_events
        SET status = 'COMPLETED'
        WHERE status IN ('PENDING', 'APPROVED');
    """)

    # 3. Close active sessions
    await execute("""
        UPDATE sessions
        SET status = 'CLOSED', end_time = CURRENT_TIMESTAMP, close_reason = 'Admin Master Reset'
        WHERE status = 'ACTIVE';
    """)

    # 4. Clean taskpool
    await execute("DELETE FROM taskpool_entries;")

    # 5. Restore all PCs to AVAILABLE (except MAINTENANCE)
    await execute("""
        UPDATE pcs
        SET state = 'AVAILABLE', updated_at = CURRENT_TIMESTAMP
        WHERE state != 'MAINTENANCE';
    """)

    return {
        "status": "success",
        "message": "All holds, reservations, and club events cleared. All workstations restored to AVAILABLE for walk-in kiosks."
    }


