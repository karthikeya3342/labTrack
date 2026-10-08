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
async def workstation_close(req: AgentCloseRequest):
    success = await fetch_val(
        "SELECT fn_close_session($1, $2);",
        req.session_id,
        req.reason
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active session {req.session_id} not found"
        )
    return {"status": "closed", "session_id": req.session_id, "reason": req.reason}

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

    # Check session state
    session_active = False
    if req.current_session_id:
        sess = await fetch_one("SELECT status FROM sessions WHERE id = $1", req.current_session_id)
        if sess and sess["status"] == "ACTIVE":
            session_active = True

    return {
        "status": "ack",
        "hostname": req.hostname,
        "state": pc["state"],
        "session_active": session_active,
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
