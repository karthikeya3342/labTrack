from fastapi import APIRouter, HTTPException, status
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import json
from backend.app.models.schemas import LockStateResponse
from backend.app.core.database import fetch_all, fetch_one

router = APIRouter(prefix="/pcs", tags=["Workstations"])

@router.get("/labs")
async def get_labs():
    labs = await fetch_all("""
        SELECT l.id, l.name, l.code, l.capacity, l.location, l.has_gpu, l.description,
               d.name as department_name,
               COUNT(p.id) as total_pcs,
               COUNT(p.id) FILTER (WHERE p.state = 'AVAILABLE') as available_pcs,
               COUNT(p.id) FILTER (WHERE p.state = 'HELD') as held_pcs,
               COUNT(p.id) FILTER (WHERE p.state = 'OCCUPIED') as occupied_pcs,
               COUNT(p.id) FILTER (WHERE p.state = 'MAINTENANCE') as maintenance_pcs
        FROM labs l
        LEFT JOIN departments d ON d.id = l.department_id
        LEFT JOIN pcs p ON p.lab_id = l.id
        GROUP BY l.id, d.name
        ORDER BY l.id
    """)
    return labs

@router.get("")
async def get_workstations(lab_id: Optional[int] = None):
    query = """
        SELECT p.id, p.hostname, p.lab_id, l.name as lab_name, l.has_gpu,
               p.ip_address, p.state, p.specifications, p.last_heartbeat, p.maintenance_reason,
               r.id as held_reservation_id, u_res.name as held_student_name, u_res.roll_no as held_roll_no,
               r.grace_deadline as held_grace_deadline,
               s.id as active_session_id, u_sess.name as active_student_name, u_sess.roll_no as active_roll_no,
               s.start_time as session_start_time
        FROM pcs p
        JOIN labs l ON l.id = p.lab_id
        LEFT JOIN reservations r ON r.pc_id = p.id AND r.status = 'HELD'
        LEFT JOIN users u_res ON u_res.id = r.student_id
        LEFT JOIN sessions s ON s.pc_id = p.id AND s.status = 'ACTIVE'
        LEFT JOIN users u_sess ON u_sess.id = s.user_id
    """
    params = []
    if lab_id is not None:
        query += " WHERE p.lab_id = $1"
        params.append(lab_id)
    query += " ORDER BY p.hostname"

    rows = await fetch_all(query, *params)
    results = []
    for row in rows:
        specs = row["specifications"]
        if isinstance(specs, str):
            try:
                specs = json.loads(specs)
            except Exception:
                specs = {}
        results.append({
            "id": row["id"],
            "hostname": row["hostname"],
            "lab_id": row["lab_id"],
            "lab_name": row["lab_name"],
            "has_gpu": row["has_gpu"],
            "ip_address": row["ip_address"],
            "state": row["state"],
            "specifications": specs,
            "last_heartbeat": row["last_heartbeat"],
            "maintenance_reason": row["maintenance_reason"],
            "held_info": {
                "reservation_id": row["held_reservation_id"],
                "student_name": row["held_student_name"],
                "roll_no": row["held_roll_no"],
                "grace_deadline": row["held_grace_deadline"]
            } if row["state"] == "HELD" and row["held_reservation_id"] else None,
            "active_session": {
                "session_id": row["active_session_id"],
                "student_name": row["active_student_name"],
                "roll_no": row["active_roll_no"],
                "start_time": row["session_start_time"]
            } if row["state"] == "OCCUPIED" and row["active_session_id"] else None
        })
    return results

@router.get("/{hostname}/lock-state", response_model=LockStateResponse)
async def get_pc_lock_state(hostname: str):
    pc = await fetch_one("""
        SELECT p.id, p.hostname, p.state, p.lab_id, l.name as lab_name
        FROM pcs p
        JOIN labs l ON l.id = p.lab_id
        WHERE p.hostname = $1
    """, hostname)

    if not pc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation {hostname} not found"
        )

    state = pc["state"]
    resp = LockStateResponse(
        hostname=pc["hostname"],
        state=state,
        lab_id=pc["lab_id"],
        lab_name=pc["lab_name"],
        message=f"Workstation {state}"
    )

    now = datetime.now(timezone.utc)

    if state == "HELD":
        # Fetch the held reservation
        res = await fetch_one("""
            SELECT r.id, r.grace_deadline, u.name as student_name, u.roll_no
            FROM reservations r
            JOIN users u ON u.id = r.student_id
            WHERE r.pc_id = $1 AND r.status = 'HELD'
            ORDER BY r.created_at DESC
            LIMIT 1
        """, pc["id"])
        if res:
            resp.reserved_student_name = res["student_name"]
            resp.reserved_roll_no = res["roll_no"]
            resp.grace_deadline = res["grace_deadline"]
            if res["grace_deadline"]:
                diff = (res["grace_deadline"] - now).total_seconds()
                resp.remaining_grace_seconds = max(0, int(diff))
            resp.message = f"🔒 Workstation Reserved for {res['student_name']} ({res['roll_no']})"
        else:
            resp.state = "AVAILABLE"
            resp.message = "🟢 Workstation Available (Walk-in Permitted)"

    elif state == "AVAILABLE":
        resp.message = "🟢 Workstation Available (Walk-in Permitted)"

    elif state == "OCCUPIED":
        sess = await fetch_one("""
            SELECT s.id, s.start_time, u.name as student_name, u.roll_no,
                   ts.cpu_percent, ts.memory_percent
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            LEFT JOIN telemetry_samples ts ON ts.session_id = s.id
            WHERE s.pc_id = $1 AND s.status = 'ACTIVE'
            ORDER BY ts.recorded_at DESC NULLS LAST
            LIMIT 1
        """, pc["id"])
        if sess:
            resp.active_session = {
                "session_id": sess["id"],
                "student_name": sess["student_name"],
                "roll_no": sess["roll_no"],
                "start_time": sess["start_time"],
                "cpu_percent": float(sess["cpu_percent"] or 0.0),
                "memory_percent": float(sess["memory_percent"] or 0.0)
            }
            resp.message = f"Workstation Occupied by {sess['student_name']}"

    elif state == "MAINTENANCE":
        resp.message = "Workstation Under Maintenance"

    return resp
