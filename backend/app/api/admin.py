from fastapi import APIRouter, HTTPException, status, Depends
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from backend.app.core.security import get_current_user_token_payload
from backend.app.core.database import fetch_all, fetch_one, execute, fetch_val
from backend.app.core.lifecycle import reap_expired_allocations
from backend.app.models.schemas import AdminDedicatedReservationRequest, AdminExtendReservationRequest

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

# --- Dedicated Student Workstation Reservations ---

@router.get("/students/search")
async def search_students(
    q: str = "",
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Search students by roll number or name for dedicated workstation reservation assignment.
    """
    verify_admin(payload)
    query = f"%{q.strip()}%" if q.strip() else "%"
    users = await fetch_all("""
        SELECT id, roll_no, name, email, role, is_active
        FROM users
        WHERE (roll_no ILIKE $1 OR name ILIKE $1 OR email ILIKE $1)
          AND is_active = TRUE
        ORDER BY roll_no ASC
        LIMIT 20;
    """, query)
    return users


def format_time_window_display(st: datetime, et: datetime) -> str:
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    st_ist = st.astimezone(ist_tz)
    et_ist = et.astimezone(ist_tz)
    if st_ist.date() == et_ist.date():
        return f"{st_ist.strftime('%b %d, %Y')} ({st_ist.strftime('%I:%M %p')} – {et_ist.strftime('%I:%M %p')})"
    return f"{st_ist.strftime('%b %d, %Y')} – {et_ist.strftime('%b %d, %Y (%I:%M %p)')}"

def format_remaining_display(remaining_seconds: int) -> str:
    if remaining_seconds <= 0:
        return "Expired"
    days = remaining_seconds // 86400
    hours = (remaining_seconds % 86400) // 3600
    mins = (remaining_seconds % 3600) // 60
    if days >= 30:
        months = days // 30
        rem_d = days % 30
        return f"{months} mo {rem_d}d remaining" if rem_d > 0 else f"{months} month{'s' if months > 1 else ''} remaining"
    if days > 1:
        return f"{days} days remaining" if hours == 0 else f"{days}d {hours}h remaining"
    if days == 1:
        return f"1 day {hours}h remaining"
    if hours > 0:
        return f"{hours}h {mins}m remaining"
    return f"{mins} min remaining"

@router.get("/reservations/dedicated")
async def list_dedicated_reservations(
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    List all active, pending, and historical dedicated workstation reservations created by administrators.
    """
    verify_admin(payload)
    await reap_expired_allocations()

    now = datetime.now(timezone.utc)
    rows = await fetch_all("""
        SELECT r.id, r.pc_id, p.hostname, p.lab_id, l.name as lab_name,
               r.student_id, u.name as student_name, u.roll_no, u.email as student_email,
               lower(r.time_range) as start_time,
               upper(r.time_range) as end_time,
               r.status, r.notes, r.allocation_basis, r.grace_deadline,
               r.created_at,
               p.state as pc_state,
               s.id as active_session_id
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        JOIN labs l ON l.id = p.lab_id
        JOIN users u ON u.id = r.student_id
        LEFT JOIN sessions s ON s.reservation_id = r.id AND s.status = 'ACTIVE'
        WHERE r.allocation_basis = 'ADMIN_DEDICATED' OR r.notes LIKE 'Admin Dedicated%'
        ORDER BY (r.status IN ('HELD', 'ACTIVE', 'PENDING')) DESC, r.created_at DESC
        LIMIT 100;
    """)

    results = []
    for row in rows:
        st = row["start_time"]
        et = row["end_time"]
        if st and st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
        if et and et.tzinfo is None:
            et = et.replace(tzinfo=timezone.utc)

        remaining_seconds = 0
        if et and et > now and row["status"] in ("HELD", "ACTIVE", "PENDING"):
            remaining_seconds = max(0, int((et - now).total_seconds()))

        time_str = format_time_window_display(st, et) if (st and et) else ""
        rem_str = format_remaining_display(remaining_seconds)

        # Parse structured purpose and reason from notes
        purpose = "Academic Research Work / Thesis"
        reason = ""
        raw_notes = row["notes"] or ""
        if "[" in raw_notes and "]" in raw_notes:
            purpose = raw_notes.split("[")[1].split("]")[0].strip()
            after_bracket = raw_notes.split("]", 1)[1].strip()
            if after_bracket.startswith("- "):
                reason = after_bracket[2:].strip()
            elif after_bracket.startswith(": "):
                reason = after_bracket[2:].strip()
            else:
                reason = after_bracket
        elif ":" in raw_notes:
            parts = raw_notes.split(":", 1)
            purpose = parts[1].split("|")[0].strip() if len(parts) > 1 else "Academic Research"
            if "|" in raw_notes:
                reason = raw_notes.split("|", 1)[1].strip()
        else:
            reason = raw_notes

        results.append({
            "id": row["id"],
            "pc_id": row["pc_id"],
            "hostname": row["hostname"],
            "lab_id": row["lab_id"],
            "lab_name": row["lab_name"],
            "student_id": row["student_id"],
            "student_name": row["student_name"],
            "roll_no": row["roll_no"],
            "student_email": row["student_email"],
            "start_time": st.isoformat() if st else None,
            "end_time": et.isoformat() if et else None,
            "time_window": time_str,
            "remaining_seconds": remaining_seconds,
            "remaining_display": rem_str,
            "purpose": purpose,
            "reason": reason,
            "status": row["status"],
            "notes": row["notes"],
            "pc_state": row["pc_state"],
            "active_session_id": row["active_session_id"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None
        })

    return results


@router.post("/reservations/dedicated")
async def create_dedicated_reservation(
    req: AdminDedicatedReservationRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Reserve a workstation exclusively for a specific student for a given time window.
    Handles auto-allocation, clash prevention, active session preemption, and kiosk lock status.
    """
    verify_admin(payload)
    await reap_expired_allocations()

    # 1. Identify and validate student
    clean_ident = req.student_identifier.strip()
    student = await fetch_one("""
        SELECT id, roll_no, name, email, role, is_active
        FROM users
        WHERE (roll_no ILIKE $1 OR email ILIKE $1) AND is_active = TRUE
        LIMIT 1;
    """, clean_ident)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with identifier '{clean_ident}' not found or inactive."
        )

    # 2. Compute time window
    now = datetime.now(timezone.utc)
    start_time = req.start_time or now
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    if req.end_time:
        end_time = req.end_time
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
    else:
        days = req.duration_days or 0
        hours = req.duration_hours or 0
        minutes = req.duration_minutes or 0
        if days > 0 or hours > 0 or minutes > 0:
            total_delta = timedelta(days=days, hours=hours, minutes=minutes)
        else:
            total_delta = timedelta(days=7) # Default 7 days for academic workstation reservation
        end_time = start_time + total_delta

    if end_time <= start_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reservation end time must be after start time."
        )

    if end_time <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reservation end time cannot be in the past."
        )

    # 3. Prevent double-booking: Check if student already has a reservation on another PC during this window
    student_clash = await fetch_one("""
        SELECT r.id, p.hostname, lower(r.time_range) as st, upper(r.time_range) as et
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        WHERE r.student_id = $1
          AND r.status IN ('PENDING', 'HELD', 'ACTIVE')
          AND r.time_range && tstzrange($2, $3, '[)')
        LIMIT 1;
    """, student["id"], start_time, end_time)
    if student_clash:
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        st_ist = student_clash["st"].astimezone(ist_tz).strftime('%I:%M %p')
        et_ist = student_clash["et"].astimezone(ist_tz).strftime('%I:%M %p')
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Student {student['name']} ({student['roll_no']}) already has an active reservation on {student_clash['hostname']} ({st_ist} - {et_ist})."
        )

    # 4. Resolve Workstation (explicit target or auto-allocate from lab)
    target_pc = None
    if req.pc_id or req.hostname:
        if req.pc_id:
            target_pc = await fetch_one("SELECT id, hostname, lab_id, state FROM pcs WHERE id = $1", req.pc_id)
        else:
            target_pc = await fetch_one("SELECT id, hostname, lab_id, state FROM pcs WHERE hostname = $1", req.hostname.strip())
        if not target_pc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specified workstation not found.")
        if target_pc["state"] == "MAINTENANCE":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Workstation {target_pc['hostname']} is flagged for hardware maintenance.")
    else:
        # Auto-pick best PC in requested lab (or any lab)
        target_pc = await fetch_one("""
            SELECT p.id, p.hostname, p.lab_id, p.state
            FROM pcs p
            WHERE ($1::int IS NULL OR p.lab_id = $1)
              AND p.state != 'MAINTENANCE'
              AND NOT EXISTS (
                  SELECT 1 FROM reservations r
                  WHERE r.pc_id = p.id
                    AND r.status IN ('PENDING', 'HELD', 'ACTIVE')
                    AND r.time_range && tstzrange($2, $3, '[)')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM club_events ce
                  WHERE (ce.lab_id = p.lab_id OR ce.secondary_lab_id = p.lab_id)
                    AND ce.status = 'APPROVED'
                    AND ce.time_range && tstzrange($2, $3, '[)')
              )
            ORDER BY (p.state = 'AVAILABLE') DESC, p.id ASC
            LIMIT 1;
        """, req.lab_id, start_time, end_time)

        if not target_pc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No available workstations in the specified lab without schedule conflicts for this time window."
            )

    pc_id = target_pc["id"]

    # 5. Check PC clash with approved Club Events
    club_clash = await fetch_one("""
        SELECT ce.id, ce.title, c.name as club_name
        FROM club_events ce
        JOIN clubs c ON c.id = ce.club_id
        WHERE (ce.lab_id = $1 OR ce.secondary_lab_id = $1)
          AND ce.status = 'APPROVED'
          AND ce.time_range && tstzrange($2, $3, '[)')
        LIMIT 1;
    """, target_pc["lab_id"], start_time, end_time)
    if club_clash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workstation {target_pc['hostname']} is in a laboratory reserved for club event: '{club_clash['club_name']} - {club_clash['title']}'."
        )

    # 6. Check PC clash with other reservations
    pc_res_clash = await fetch_one("""
        SELECT r.id, r.status, r.notes, u.name as reserved_name, u.roll_no,
               lower(r.time_range) as st, upper(r.time_range) as et
        FROM reservations r
        LEFT JOIN users u ON u.id = r.student_id
        WHERE r.pc_id = $1
          AND r.status IN ('PENDING', 'HELD', 'ACTIVE')
          AND r.time_range && tstzrange($2, $3, '[)')
        LIMIT 1;
    """, pc_id, start_time, end_time)
    if pc_res_clash:
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        st_ist = pc_res_clash["st"].astimezone(ist_tz).strftime('%I:%M %p')
        et_ist = pc_res_clash["et"].astimezone(ist_tz).strftime('%I:%M %p')
        who = f"{pc_res_clash['reserved_name']} ({pc_res_clash['roll_no']})" if pc_res_clash["reserved_name"] else (pc_res_clash["notes"] or "another session")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workstation {target_pc['hostname']} is already reserved by {who} from {st_ist} to {et_ist}."
        )

    # 7. Check if PC has an active walk-in session right now
    is_immediate = (start_time <= now + timedelta(minutes=10) and end_time > now)
    if is_immediate:
        active_sess = await fetch_one("""
            SELECT s.id, s.user_id, u.name as current_user_name, u.roll_no as current_roll_no
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.pc_id = $1 AND s.status = 'ACTIVE'
            LIMIT 1;
        """, pc_id)

        if active_sess:
            if active_sess["user_id"] == student["id"]:
                # The student themselves is already on this machine
                pass
            elif req.force_preempt:
                # Administrator override: Preempt current walk-in session
                await fetch_val(
                    "SELECT fn_close_session($1, $2);",
                    active_sess["id"],
                    f"Preempted by Administrator for Dedicated Student Reservation ({student['roll_no']})"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Workstation {target_pc['hostname']} is currently in use by {active_sess['current_user_name']} ({active_sess['current_roll_no']}). Enable 'Force Preempt' to reassign or select another machine."
                )

    # 8. Create Dedicated Reservation
    init_status = "HELD" if is_immediate else "PENDING"
    purpose = (req.purpose or "Academic Research Work / Thesis").strip()
    reason_text = req.reason.strip() if req.reason else (req.notes.strip() if req.notes else "Dedicated Workstation Allocation")
    notes = f"Admin Dedicated: [{purpose}] - {reason_text}"

    res_id = await fetch_val("""
        INSERT INTO reservations (
            student_id, pc_id, task_type, time_range, status,
            grace_deadline, priority_score, allocation_basis, notes
        ) VALUES (
            $1, $2, 'Coursework', tstzrange($3, $4, '[)'), $5,
            $4, 100, 'ADMIN_DEDICATED', $6
        ) RETURNING id;
    """, student["id"], pc_id, start_time, end_time, init_status, notes)

    # 9. Update PC State if immediate
    if is_immediate:
        await execute("""
            UPDATE pcs
            SET state = 'HELD', updated_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND state != 'OCCUPIED' AND state != 'MAINTENANCE';
        """, pc_id)

    # 10. Audit log
    admin_id = int(payload.get("sub", 1))
    await execute("""
        INSERT INTO audit_logs (event_type, user_id, pc_id, details)
        VALUES ('ADMIN_DEDICATED_RESERVATION', $1, $2, $3::jsonb);
    """, admin_id, pc_id, f'{{"reservation_id": {res_id}, "student_id": {student["id"]}, "student_roll_no": "{student["roll_no"]}", "force_preempt": {str(req.force_preempt).lower()}}}')

    lab_info = await fetch_one("SELECT name FROM labs WHERE id = $1", target_pc["lab_id"])

    remaining_seconds = max(0, int((end_time - now).total_seconds()))
    remaining_display = format_remaining_display(remaining_seconds)
    time_window = format_time_window_display(start_time, end_time)

    return {
        "status": "success",
        "reservation_id": res_id,
        "pc_id": pc_id,
        "hostname": target_pc["hostname"],
        "lab_name": lab_info["name"] if lab_info else "Campus Lab",
        "student_name": student["name"],
        "roll_no": student["roll_no"],
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "time_window": time_window,
        "remaining_seconds": remaining_seconds,
        "remaining_display": remaining_display,
        "purpose": purpose,
        "reason": reason_text,
        "reservation_status": init_status,
        "message": f"Workstation {target_pc['hostname']} dedicated to {student['name']} ({student['roll_no']}) for '{purpose}' until {end_time.strftime('%b %d, %Y (%I:%M %p)')} ({remaining_display})."
    }


@router.post("/reservations/{reservation_id}/extend")
async def extend_dedicated_reservation(
    reservation_id: int,
    req: AdminExtendReservationRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Extend an active or held dedicated reservation.
    Validates clashes against upcoming practical labs, club events, and other bookings.
    """
    verify_admin(payload)
    await reap_expired_allocations()

    res = await fetch_one("""
        SELECT r.id, r.pc_id, r.student_id, p.hostname, p.lab_id, l.name as lab_name,
               u.name as student_name, u.roll_no,
               lower(r.time_range) as start_time, upper(r.time_range) as end_time,
               r.status, r.notes
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        JOIN labs l ON l.id = p.lab_id
        JOIN users u ON u.id = r.student_id
        WHERE r.id = $1;
    """, reservation_id)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found.")

    if res["status"] not in ("PENDING", "HELD", "ACTIVE"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot extend {res['status']} reservation.")

    cur_end = res["end_time"]
    if cur_end.tzinfo is None:
        cur_end = cur_end.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    base_time = max(cur_end, now)

    if req.new_end_time:
        new_end = req.new_end_time
        if new_end.tzinfo is None:
            new_end = new_end.replace(tzinfo=timezone.utc)
    else:
        days = req.additional_days or 0
        hours = req.additional_hours or 0
        minutes = req.additional_minutes or 0
        if days > 0 or hours > 0 or minutes > 0:
            delta = timedelta(days=days, hours=hours, minutes=minutes)
        else:
            delta = timedelta(days=5) # Default 5 days extension
        new_end = base_time + delta

    if new_end <= cur_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New end time must be later than current end time."
        )

    # Collision Check 1: Other reservations on this PC during extension window [cur_end, new_end)
    res_clash = await fetch_one("""
        SELECT r2.id, r2.notes, u2.name as clash_name, u2.roll_no as clash_roll,
               lower(r2.time_range) as st
        FROM reservations r2
        LEFT JOIN users u2 ON u2.id = r2.student_id
        WHERE r2.pc_id = $1
          AND r2.id != $2
          AND r2.status IN ('PENDING', 'HELD', 'ACTIVE')
          AND r2.time_range && tstzrange($3, $4, '[)')
        LIMIT 1;
    """, res["pc_id"], reservation_id, cur_end, new_end)
    if res_clash:
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        st_ist = res_clash["st"].astimezone(ist_tz).strftime('%b %d, %I:%M %p')
        who = f"{res_clash['clash_name']} ({res_clash['clash_roll']})" if res_clash["clash_name"] else (res_clash["notes"] or "another booking")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot extend: Workstation {res['hostname']} has an upcoming reservation for {who} starting at {st_ist}."
        )

    # Collision Check 2: Upcoming approved club events in that lab during extension window
    club_clash = await fetch_one("""
        SELECT ce.id, ce.title, c.name as club_name, lower(ce.time_range) as st
        FROM club_events ce
        JOIN clubs c ON c.id = ce.club_id
        WHERE (ce.lab_id = $1 OR ce.secondary_lab_id = $1)
          AND ce.status = 'APPROVED'
          AND ce.time_range && tstzrange($2, $3, '[)')
        LIMIT 1;
    """, res["lab_id"], cur_end, new_end)
    if club_clash:
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        st_ist = club_clash["st"].astimezone(ist_tz).strftime('%b %d, %I:%M %p')
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot extend: Laboratory is scheduled for club event '{club_clash['club_name']} - {club_clash['title']}' starting at {st_ist}."
        )

    # Record academic extension reason in notes
    ext_reason = (req.reason or "Academic project / research milestone extension").strip()
    existing_notes = res["notes"] or "Admin Dedicated"
    updated_notes = f"{existing_notes} | Extended: {ext_reason}"

    # Apply extension: update time_range, grace_deadline, and notes
    await execute("""
        UPDATE reservations
        SET time_range = tstzrange(lower(time_range), $1, '[)'),
            grace_deadline = $1,
            notes = $2,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = $3;
    """, new_end, updated_notes, reservation_id)

    # Ensure PC state remains HELD if not OCCUPIED
    await execute("""
        UPDATE pcs
        SET state = 'HELD', updated_at = CURRENT_TIMESTAMP
        WHERE id = $1 AND state = 'AVAILABLE';
    """, res["pc_id"])

    remaining_seconds = max(0, int((new_end - now).total_seconds()))
    remaining_minutes = max(0, int(remaining_seconds / 60))
    remaining_display = format_remaining_display(remaining_seconds)
    time_window = format_time_window_display(res["start_time"], new_end)

    return {
        "status": "success",
        "reservation_id": reservation_id,
        "hostname": res["hostname"],
        "student_name": res["student_name"],
        "roll_no": res["roll_no"],
        "new_end_time": new_end.isoformat(),
        "time_window": time_window,
        "remaining_seconds": remaining_seconds,
        "remaining_minutes": remaining_minutes,
        "remaining_display": remaining_display,
        "extension_reason": ext_reason,
        "message": f"Reservation on {res['hostname']} extended until {new_end.strftime('%b %d, %Y (%I:%M %p)')} ({remaining_display}) for: {ext_reason}."
    }


@router.post("/reservations/{reservation_id}/release")
async def release_dedicated_reservation(
    reservation_id: int,
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Release / cancel a dedicated reservation early, terminating any active session
    and restoring the workstation to AVAILABLE walk-in kiosk mode.
    """
    verify_admin(payload)

    res = await fetch_one("""
        SELECT r.id, r.pc_id, r.student_id, p.hostname, r.status
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        WHERE r.id = $1;
    """, reservation_id)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found.")

    # 1. Close any active session on this reservation or PC
    active_sess = await fetch_one("""
        SELECT id FROM sessions
        WHERE (reservation_id = $1 OR (pc_id = $2 AND user_id = $3)) AND status = 'ACTIVE'
        LIMIT 1;
    """, reservation_id, res["pc_id"], res["student_id"])

    if active_sess:
        await fetch_val("SELECT fn_close_session($1, $2);", active_sess["id"], "Released early by Administrator")

    # 2. Mark reservation completed
    await execute("""
        UPDATE reservations
        SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
        WHERE id = $1;
    """, reservation_id)

    # 3. Restore PC state to AVAILABLE (if no other upcoming hold or maintenance)
    now = datetime.now(timezone.utc)
    other_hold = await fetch_one("""
        SELECT id FROM reservations
        WHERE pc_id = $1
          AND status = 'HELD'
          AND upper(time_range) > $2
          AND lower(time_range) <= ($2 + INTERVAL '10 minutes')
        LIMIT 1;
    """, res["pc_id"], now)

    if not other_hold:
        await execute("""
            UPDATE pcs
            SET state = 'AVAILABLE', updated_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND state != 'MAINTENANCE';
        """, res["pc_id"])

    return {
        "status": "success",
        "reservation_id": reservation_id,
        "hostname": res["hostname"],
        "message": f"Workstation {res['hostname']} released and restored to AVAILABLE walk-in kiosk mode."
    }



