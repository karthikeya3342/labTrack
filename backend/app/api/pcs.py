from fastapi import APIRouter, HTTPException, status
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import json
from backend.app.models.schemas import LockStateResponse
from backend.app.core.database import fetch_all, fetch_one, execute
from backend.app.core.lifecycle import reap_expired_allocations

router = APIRouter(prefix="/pcs", tags=["Workstations"])

@router.get("/labs")
async def get_labs():
    await reap_expired_allocations()
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
    await reap_expired_allocations()
    query = """
        SELECT p.id, p.hostname, p.lab_id, l.name as lab_name, l.has_gpu,
               p.ip_address, p.state, p.specifications, p.last_heartbeat, p.maintenance_reason,
               r.id as held_reservation_id, u_res.name as held_student_name, u_res.roll_no as held_roll_no,
               u_res.role as held_user_role, r.batch_name as held_batch_name, r.notes as held_notes,
               r.task_type as held_task_type, r.club_event_id as held_club_event_id,
               c.name as held_club_name, ce.title as held_event_title,
               lower(r.time_range) as held_start_time, upper(r.time_range) as held_end_time,
               r.grace_deadline as held_grace_deadline,
               s.id as active_session_id, u_sess.name as active_student_name, u_sess.roll_no as active_roll_no,
               s.start_time as session_start_time, r_sess.notes as active_notes,
               ce_sess.title as active_event_title, c_sess.name as active_club_name,
               ts.cpu_percent as ts_cpu, ts.memory_percent as ts_mem,
               ts.memory_rss_bytes as ts_rss, ts.process_count as ts_procs,
               ts.load_average as ts_load, ts.recorded_at as ts_time
        FROM pcs p
        JOIN labs l ON l.id = p.lab_id
        LEFT JOIN reservations r ON r.pc_id = p.id AND r.status = 'HELD'
                                AND lower(r.time_range) <= (CURRENT_TIMESTAMP + INTERVAL '10 minutes')
                                AND upper(r.time_range) > CURRENT_TIMESTAMP
        LEFT JOIN users u_res ON u_res.id = r.student_id
        LEFT JOIN club_events ce ON ce.id = r.club_event_id
        LEFT JOIN clubs c ON c.id = ce.club_id
        LEFT JOIN sessions s ON s.pc_id = p.id AND s.status = 'ACTIVE'
        LEFT JOIN users u_sess ON u_sess.id = s.user_id
        LEFT JOIN reservations r_sess ON r_sess.id = s.reservation_id
        LEFT JOIN club_events ce_sess ON ce_sess.id = s.club_event_id
        LEFT JOIN clubs c_sess ON c_sess.id = ce_sess.club_id
        LEFT JOIN LATERAL (
            SELECT cpu_percent, memory_percent, memory_rss_bytes, process_count, load_average, recorded_at
            FROM telemetry_samples
            WHERE pc_id = p.id
            ORDER BY recorded_at DESC
            LIMIT 1
        ) ts ON TRUE
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

        latest_tel = None
        if row["ts_cpu"] is not None:
            latest_tel = {
                "cpu_percent": round(float(row["ts_cpu"]), 1),
                "memory_percent": round(float(row["ts_mem"] or 0.0), 1),
                "memory_rss_mb": round(float(row["ts_rss"] or 0) / (1024 * 1024), 1),
                "process_count": int(row["ts_procs"] or 0),
                "load_average": round(float(row["ts_load"] or 0.0), 2),
                "recorded_at": row["ts_time"].isoformat() if row["ts_time"] else None
            }

        held_info = None
        if row["state"] == "HELD" and row["held_reservation_id"]:
            time_str = ""
            st_iso = None
            et_iso = None
            if row["held_start_time"] and row["held_end_time"]:
                st = row["held_start_time"]
                et = row["held_end_time"]
                if st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)
                if et.tzinfo is None:
                    et = et.replace(tzinfo=timezone.utc)
                st_iso = st.isoformat()
                et_iso = et.isoformat()
                ist_tz = timezone(timedelta(hours=5, minutes=30))
                st_ist = st.astimezone(ist_tz)
                et_ist = et.astimezone(ist_tz)
                time_str = f"{st_ist.strftime('%I:%M %p')} - {et_ist.strftime('%I:%M %p')}"
            
            if row["held_club_event_id"]:
                held_info = {
                    "reservation_id": row["held_reservation_id"],
                    "hold_type": "club",
                    "who": row["held_club_name"] or "Technical Club",
                    "purpose": f"Event: {row['held_event_title']}",
                    "event_title": row["held_event_title"],
                    "start_time": st_iso,
                    "end_time": et_iso,
                    "time_window": time_str,
                    "grace_deadline": row["held_grace_deadline"].isoformat() if row["held_grace_deadline"] else None
                }
            elif row["held_batch_name"] or (row["held_user_role"] in ("faculty", "admin") and "Faculty" in (row["held_notes"] or "")):
                held_info = {
                    "reservation_id": row["held_reservation_id"],
                    "hold_type": "faculty",
                    "who": f"Prof. {row['held_student_name']}" if row["held_student_name"] else "Faculty Session",
                    "purpose": row["held_notes"] or f"Practical Lab ({row['held_batch_name'] or ''})",
                    "batch_name": row["held_batch_name"],
                    "start_time": st_iso,
                    "end_time": et_iso,
                    "time_window": time_str,
                    "grace_deadline": row["held_grace_deadline"].isoformat() if row["held_grace_deadline"] else None
                }
            else:
                held_info = {
                    "reservation_id": row["held_reservation_id"],
                    "hold_type": "student",
                    "who": f"{row['held_student_name']} ({row['held_roll_no']})" if row["held_student_name"] else "Reserved Student",
                    "student_name": row["held_student_name"],
                    "roll_no": row["held_roll_no"],
                    "purpose": row["held_notes"] or row["held_task_type"] or "Individual Booking",
                    "start_time": st_iso,
                    "end_time": et_iso,
                    "time_window": time_str,
                    "grace_deadline": row["held_grace_deadline"].isoformat() if row["held_grace_deadline"] else None
                }

        active_session = None
        if row["state"] == "OCCUPIED" and row["active_session_id"]:
            active_session = {
                "session_id": row["active_session_id"],
                "who": f"{row['active_student_name']} ({row['active_roll_no']})",
                "student_name": row["active_student_name"],
                "roll_no": row["active_roll_no"],
                "purpose": row["active_notes"] or (f"Club: {row['active_club_name']}" if row["active_club_name"] else "Active Workstation Session"),
                "start_time": row["session_start_time"].isoformat() if row["session_start_time"] else None
            }

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
            "latest_telemetry": latest_tel,
            "held_info": held_info,
            "active_session": active_session
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
    threshold = now + timedelta(minutes=10)

    # 1. First, check if there is an active or upcoming approved club event for this PC's lab
    club_event = await fetch_one("""
        SELECT ce.id as event_id, ce.title as event_title,
               c.name as club_name, c.slug as club_slug, c.logo_url as club_logo_url,
               lower(ce.time_range) as start_time, upper(ce.time_range) as end_time
        FROM club_events ce
        JOIN clubs c ON c.id = ce.club_id
        WHERE (ce.lab_id = $1 OR ce.secondary_lab_id = $1)
          AND ce.status = 'APPROVED'
          AND upper(ce.time_range) > $2
          AND lower(ce.time_range) <= $3
        ORDER BY ce.created_at DESC
        LIMIT 1
    """, pc["lab_id"], now, threshold)

    if state not in ("OCCUPIED", "MAINTENANCE") and club_event:
        resp.state = "HELD"
        resp.is_club_event = True
        resp.club_name = club_event["club_name"]
        resp.club_slug = club_event["club_slug"]
        resp.club_logo_url = club_event["club_logo_url"]
        resp.event_title = club_event["event_title"]
        resp.event_id = club_event["event_id"]
        resp.purpose = f"Technical Club Event: {club_event['event_title']}"
        resp.message = f"⚡ {club_event['club_name']}: {club_event['event_title']}"
        if pc["state"] != "HELD":
            await execute("UPDATE pcs SET state = 'HELD', updated_at = CURRENT_TIMESTAMP WHERE id = $1", pc["id"])
    elif state == "HELD":
        # Fetch unexpired individual student reservation, faculty session, or club event
        res = await fetch_one("""
            SELECT r.id, r.grace_deadline, r.batch_name, r.notes, r.task_type,
                   u.name as student_name, u.roll_no, u.role as user_role,
                   r.club_event_id, ce.title as event_title, c.name as club_name,
                   c.slug as club_slug, c.logo_url as club_logo_url,
                   lower(r.time_range) as start_time, upper(r.time_range) as end_time
            FROM reservations r
            LEFT JOIN users u ON u.id = r.student_id
            LEFT JOIN club_events ce ON ce.id = r.club_event_id
            LEFT JOIN clubs c ON c.id = ce.club_id
            WHERE r.pc_id = $1 AND r.status = 'HELD'
              AND lower(r.time_range) <= $3
              AND upper(r.time_range) > $2
              AND (r.grace_deadline IS NULL OR r.grace_deadline > $2)
            ORDER BY r.created_at DESC
            LIMIT 1
        """, pc["id"], now, threshold)
        if res:
            if res["club_event_id"]:
                resp.is_club_event = True
                resp.club_name = res["club_name"]
                resp.club_slug = res["club_slug"]
                resp.club_logo_url = res["club_logo_url"]
                resp.event_title = res["event_title"]
                resp.event_id = res["club_event_id"]
                resp.purpose = f"Technical Club Event: {res['event_title']}"
                resp.message = f"⚡ {res['club_name']}: {res['event_title']}"
            elif res["batch_name"] or res["user_role"] == "faculty":
                resp.is_faculty_lab = True
                resp.faculty_name = res["student_name"] or "Faculty Member"
                clean_notes = (res["notes"] or "").replace("Faculty Extra Lab: ", "")
                resp.course_name = clean_notes if clean_notes else "Practical Lab"
                resp.batch_name = res["batch_name"] or "Enrolled Cohort"
                resp.purpose = res["notes"] or f"Faculty Lab ({resp.batch_name})"
                resp.message = f"🎓 Faculty Lab: {resp.course_name} ({resp.batch_name}) - {resp.faculty_name}"
            else:
                resp.reserved_student_name = res["student_name"]
                resp.reserved_roll_no = res["roll_no"]
                resp.grace_deadline = res["grace_deadline"]
                resp.purpose = res["notes"] or res["task_type"] or "Workstation Booking"
                if res["grace_deadline"]:
                    diff = (res["grace_deadline"] - now).total_seconds()
                    resp.remaining_grace_seconds = max(0, int(diff))
                resp.message = f"🔒 Workstation Reserved for {res['student_name']} ({res['roll_no']})"
        else:
            # Self-healing: HELD state is stale, in the future, or grace deadline passed
            await execute("UPDATE pcs SET state = 'AVAILABLE', updated_at = CURRENT_TIMESTAMP WHERE id = $1", pc["id"])
            resp.state = "AVAILABLE"
            resp.is_club_event = False
            resp.is_faculty_lab = False
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
        else:
            # Self-healing: OCCUPIED state had no active session
            await execute("UPDATE pcs SET state = 'AVAILABLE', updated_at = CURRENT_TIMESTAMP WHERE id = $1", pc["id"])
            resp.state = "AVAILABLE"
            resp.is_club_event = False
            resp.message = "🟢 Workstation Available (Walk-in Permitted)"

    elif state == "MAINTENANCE":
        resp.message = "Workstation Under Maintenance"

    # Fetch latest telemetry for this PC
    latest_ts = await fetch_one("""
        SELECT cpu_percent, memory_percent, memory_rss_bytes, process_count, load_average, recorded_at
        FROM telemetry_samples
        WHERE pc_id = $1
        ORDER BY recorded_at DESC
        LIMIT 1
    """, pc["id"])
    if latest_ts:
        resp.latest_telemetry = {
            "cpu_percent": round(float(latest_ts["cpu_percent"]), 1),
            "memory_percent": round(float(latest_ts["memory_percent"] or 0.0), 1),
            "memory_rss_mb": round(float(latest_ts["memory_rss_bytes"] or 0) / (1024 * 1024), 1),
            "process_count": int(latest_ts["process_count"] or 0),
            "load_average": round(float(latest_ts["load_average"] or 0.0), 2),
            "recorded_at": latest_ts["recorded_at"].isoformat() if latest_ts["recorded_at"] else None
        }

    return resp
