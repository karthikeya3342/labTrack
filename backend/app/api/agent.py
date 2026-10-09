from fastapi import APIRouter, HTTPException, status
from typing import Optional
from datetime import datetime, timezone
import asyncpg
from backend.app.models.schemas import (
    AgentCheckinRequest, AgentCheckinResponse,
    AgentCloseRequest, AgentHeartbeatRequest,
    TelemetrySampleRequest
)
from backend.app.core.security import verify_password
from backend.app.core.database import fetch_one, fetch_val, execute

router = APIRouter(prefix="/agent", tags=["Workstation Agent"])

@router.post("/checkin", response_model=AgentCheckinResponse)
async def workstation_checkin(req: AgentCheckinRequest):
    # 1. Verify User Credentials
    user = await fetch_one(
        "SELECT id, roll_no, name, password_hash, role, is_active FROM users WHERE roll_no = $1 OR email = $1",
        req.roll_no
    )
    if not user or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials: student roll number / email not found"
        )

    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials: incorrect password"
        )

    # 2. Invoke Stored Procedure fn_checkin_session
    try:
        row = await fetch_one("""
            SELECT out_session_id, out_reservation_id, out_pc_id,
                   out_student_id, out_student_name, out_status, out_message
            FROM fn_checkin_session($1, $2, $3, $4);
        """, req.hostname, req.roll_no, req.cgroup_path, req.workspace_path)
    except (asyncpg.exceptions.RaiseError, asyncpg.exceptions.PostgresError) as e:
        err_msg = str(e)
        if "Access Denied" in err_msg:
            # Unauthorized student on a HELD PC
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=err_msg
            )
        elif "occupied" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=err_msg
            )
        elif "maintenance" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=err_msg
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=err_msg
            )

    return AgentCheckinResponse(
        session_id=row["out_session_id"],
        reservation_id=row["out_reservation_id"],
        pc_id=row["out_pc_id"],
        student_id=row["out_student_id"],
        student_name=row["out_student_name"],
        roll_no=req.roll_no,
        status=row["out_status"],
        message=row["out_message"]
    )

@router.post("/close")
@router.post("/session-close")
async def workstation_close(req: AgentCloseRequest):
    target_session_id = req.session_id

    # If session_id not given but hostname provided, look up active session on this PC
    if not target_session_id and req.hostname:
        sess = await fetch_one("""
            SELECT s.id FROM sessions s
            JOIN pcs p ON s.pc_id = p.id
            WHERE p.hostname = $1 AND s.status = 'ACTIVE'
            ORDER BY s.start_time DESC LIMIT 1
        """, req.hostname)
        if sess:
            target_session_id = sess["id"]
        else:
            # If no active session, only clear stuck OCCUPIED state if any
            await execute("UPDATE pcs SET state = 'AVAILABLE' WHERE hostname = $1 AND state = 'OCCUPIED'", req.hostname)
            return {"status": "no_active_session", "hostname": req.hostname, "reason": req.reason}

    if not target_session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify either session_id or hostname"
        )

    sess_info = await fetch_one("SELECT pc_id FROM sessions WHERE id = $1", target_session_id)

    success = await fetch_val(
        "SELECT fn_close_session($1, $2);",
        target_session_id,
        req.reason
    )
    if not success:
        if req.hostname:
            await execute("UPDATE pcs SET state = 'AVAILABLE' WHERE hostname = $1", req.hostname)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active session {target_session_id} not found"
        )

    # Check and trigger TaskPool auto-promotion for newly freed PC
    promotion = None
    if sess_info:
        pc = await fetch_one("SELECT id, lab_id FROM pcs WHERE id = $1", sess_info["pc_id"])
        if pc:
            from backend.app.api.scheduler import promote_next_taskpool_entry
            promotion = await promote_next_taskpool_entry(pc["id"], pc["lab_id"])

    return {
        "status": "closed",
        "session_id": target_session_id,
        "reason": req.reason,
        "promoted_waitlist_entry": promotion
    }

@router.post("/heartbeat")
async def workstation_heartbeat(req: AgentHeartbeatRequest):
    now = datetime.now(timezone.utc)
    pc = await fetch_one("SELECT id, state FROM pcs WHERE hostname = $1", req.hostname)
    if not pc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Hostname {req.hostname} unknown")

    # Update heartbeat and IP if provided
    if req.ip_address:
        await execute("UPDATE pcs SET last_heartbeat = $1, ip_address = $2 WHERE id = $3", now, req.ip_address, pc["id"])
    else:
        await execute("UPDATE pcs SET last_heartbeat = $1 WHERE id = $2", now, pc["id"])

    # Check session state for this PC
    sess = await fetch_one("""
        SELECT s.id, u.roll_no, u.name 
        FROM sessions s 
        JOIN users u ON s.user_id = u.id 
        WHERE s.pc_id = $1 AND s.status = 'ACTIVE' 
        ORDER BY s.start_time DESC LIMIT 1
    """, pc["id"])

    session_active = False
    active_sess_id = None
    active_roll = None
    active_name = None

    if sess:
        session_active = True
        active_sess_id = sess["id"]
        active_roll = sess["roll_no"]
        active_name = sess["name"]

    return {
        "status": "ack",
        "hostname": req.hostname,
        "state": pc["state"],
        "session_active": session_active,
        "active_session_id": active_sess_id,
        "active_roll_no": active_roll,
        "active_student_name": active_name,
        "server_time": now.isoformat()
    }

@router.post("/telemetry")
async def ingest_telemetry(req: TelemetrySampleRequest):
    pc = await fetch_one("SELECT id FROM pcs WHERE hostname = $1", req.hostname)
    if not pc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Hostname {req.hostname} unknown")

    await execute("""
        INSERT INTO telemetry_samples (
            session_id, pc_id, cpu_percent, memory_rss_bytes,
            memory_percent, page_faults, process_count, load_average
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """, req.session_id, pc["id"], req.cpu_percent, req.memory_rss_bytes,
         req.memory_percent, req.page_faults, req.process_count, req.load_average)

    return {"status": "recorded", "session_id": req.session_id}
