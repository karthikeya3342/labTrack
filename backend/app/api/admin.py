from fastapi import APIRouter, HTTPException, status, Depends
from typing import Optional, Dict, Any
from pydantic import BaseModel
from backend.app.core.security import get_current_user_token_payload
from backend.app.core.database import fetch_all, fetch_one, execute, fetch_val

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
    success = await fetch_val(
        "SELECT fn_close_session($1, $2);",
        session_id,
        "Force released by Administrator"
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found or already closed")
    return {"status": "force_released", "session_id": session_id}

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
    summary = await fetch_one("""
        WITH latest_samples AS (
            SELECT DISTINCT ON (pc_id)
                   pc_id, cpu_percent, memory_percent, memory_rss_bytes, load_average, recorded_at
            FROM telemetry_samples
            WHERE recorded_at >= CURRENT_TIMESTAMP - INTERVAL '1 hour'
            ORDER BY pc_id, recorded_at DESC
        )
        SELECT
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

