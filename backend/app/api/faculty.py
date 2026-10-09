from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, date, timedelta
from pydantic import BaseModel
import asyncpg
from backend.app.core.security import get_current_user_token_payload
from backend.app.core.database import fetch_all, fetch_one, execute, fetch_val

router = APIRouter(prefix="/faculty", tags=["Faculty Operations"])

class ExtraLabReservationRequest(BaseModel):
    course_name: str
    batch_name: str  # e.g., "3rd Year CSE - Section A"
    student_count: int  # e.g., 107
    allocation_strategy: Optional[str] = "SEQUENTIAL"  # "SEQUENTIAL" or "BALANCED"
    preferred_lab_id: Optional[int] = 1
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = "Extra practical / makeup lab session"

class EndFacultySessionRequest(BaseModel):
    batch_name: str

@router.post("/reserve-extra-lab")
async def reserve_extra_lab(
    req: ExtraLabReservationRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    On-Demand Extra Lab Reservation by Faculty:
    - Faculty can book whenever needed, provided lab is not already reserved by another faculty.
    - Enforces M1: Max 1 practical lab per day for this student batch.
    - Enforces M2: Requesting faculty is not double-booked.
    - Enforces M5: Cohort multi-lab allocation (e.g. 107 students partitioned across labs).
      Crucial: Spare capacity in any partially filled lab remains completely AVAILABLE for other students.
    """
    user_id = int(payload["sub"])
    role = payload.get("role", "student")

    if role not in ("faculty", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only faculty members and administrators can book extra lab sessions."
        )

    if req.start_time >= req.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start time must precede end time."
        )

    # 1. Constraint M1: Single Lab per Day for this Student Batch
    # Check if this batch already has any reservation on the same calendar day
    same_day_conflict = await fetch_one("""
        SELECT r.id, r.task_type, r.batch_name, p.hostname, l.name as lab_name,
               lower(r.time_range) as start_time
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        JOIN labs l ON l.id = p.lab_id
        WHERE r.batch_name = $1
          AND r.status IN ('PENDING', 'HELD', 'ACTIVE')
          AND (
              DATE(lower(r.time_range)) = DATE($2::timestamptz)
              OR DATE(lower(r.time_range) AT TIME ZONE 'UTC') = DATE($2::timestamptz AT TIME ZONE 'UTC')
              OR abs(extract(epoch from (lower(r.time_range) - $2::timestamptz))) <= 43200
          )
        LIMIT 1;
    """, req.batch_name, req.start_time)

    if same_day_conflict:
        conf_dt = same_day_conflict["start_time"]
        if conf_dt and conf_dt.tzinfo is None:
            conf_dt = conf_dt.replace(tzinfo=timezone.utc)
        if conf_dt:
            conf_dt = conf_dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
        time_part = conf_dt.strftime('%I:%M %p') if conf_dt else ""
        date_part = conf_dt.strftime('%Y-%m-%d') if conf_dt else req.start_time.strftime('%Y-%m-%d')
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Constraint M1 Violation: Batch '{req.batch_name}' already has a practical lab scheduled "
                f"on {date_part} ({same_day_conflict['lab_name']} at {time_part}). "
                "Indian college policy strictly caps students at at most 1 practical lab per day."
            )
        )

    # 2. Constraint M2: Requesting Faculty Clash Prevention
    # Check if this faculty member is already booking another lab simultaneously
    if role != "admin":
        faculty_conflict = await fetch_one("""
            SELECT r.id, p.hostname, l.name as lab_name
            FROM reservations r
            JOIN pcs p ON p.id = r.pc_id
            JOIN labs l ON l.id = p.lab_id
            WHERE r.student_id = $1
              AND r.status IN ('PENDING', 'HELD', 'ACTIVE')
              AND r.time_range && tstzrange($2, $3, '[)')
            LIMIT 1;
        """, user_id, req.start_time, req.end_time)

        if faculty_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Constraint M2 Violation: You already have another session booked during this time window in {faculty_conflict['lab_name']}."
            )

    # 3. Constraint M5: Cohort Multi-Lab Partitioning (e.g., 107 students)
    # Find free workstations across candidate labs during [start_time, end_time)
    labs = await fetch_all("""
        SELECT l.id, l.name, l.capacity, COUNT(p.id) as total_pcs
        FROM labs l
        JOIN pcs p ON p.lab_id = l.id
        WHERE p.state != 'MAINTENANCE'
        GROUP BY l.id
        ORDER BY CASE WHEN l.id = $1 THEN 0 ELSE 1 END, l.id ASC;
    """, req.preferred_lab_id or 1)

    lab_candidates = []
    total_available_pcs = 0

    for lab in labs:
        free_pcs_in_lab = await fetch_all("""
            SELECT p.id, p.hostname
            FROM pcs p
            WHERE p.lab_id = $1
              AND p.state != 'MAINTENANCE'
              AND NOT EXISTS (
                  SELECT 1 FROM reservations r
                  WHERE r.pc_id = p.id
                    AND r.status IN ('PENDING', 'HELD', 'ACTIVE')
                    AND r.time_range && tstzrange($2, $3, '[)')
              )
            ORDER BY p.hostname ASC;
        """, lab["id"], req.start_time, req.end_time)

        if free_pcs_in_lab:
            lab_candidates.append({
                "lab": lab,
                "free_pcs": free_pcs_in_lab
            })
            total_available_pcs += len(free_pcs_in_lab)

    if total_available_pcs < req.student_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Insufficient lab capacity across all labs. Needed {req.student_count} workstations, "
                f"but only {total_available_pcs} clash-free workstations are available for this time slot."
            )
        )

    strategy = (req.allocation_strategy or "SEQUENTIAL").upper()
    allocated_pcs = []
    lab_allocation_summary = []

    if strategy == "BALANCED":
        # Equal sharing across candidate labs
        # 1. Determine minimal subset of labs needed to seat the cohort
        chosen_candidates = []
        covered_capacity = 0
        for cand in lab_candidates:
            chosen_candidates.append(cand)
            covered_capacity += len(cand["free_pcs"])
            if covered_capacity >= req.student_count:
                break

        # 2. Distribute students evenly across chosen labs
        alloc_counts = {c["lab"]["id"]: 0 for c in chosen_candidates}
        students_remaining = req.student_count

        while students_remaining > 0:
            eligible = [c for c in chosen_candidates if alloc_counts[c["lab"]["id"]] < len(c["free_pcs"])]
            if not eligible:
                break
            min_count = min(alloc_counts[c["lab"]["id"]] for c in eligible)
            for c in eligible:
                if alloc_counts[c["lab"]["id"]] == min_count and students_remaining > 0:
                    alloc_counts[c["lab"]["id"]] += 1
                    students_remaining -= 1

        for c in chosen_candidates:
            count = alloc_counts[c["lab"]["id"]]
            taken = c["free_pcs"][:count]
            allocated_pcs.extend(taken)
            spare = len(c["free_pcs"]) - count
            lab_allocation_summary.append({
                "lab_id": c["lab"]["id"],
                "lab_name": c["lab"]["name"],
                "allocated_students": count,
                "spare_pcs_available_for_others": spare
            })
    else:
        # Sequential fill: 1st lab 100%, spillover into 2nd lab, spare in 2nd lab stays free for others
        needed_students = req.student_count
        for cand in lab_candidates:
            if needed_students <= 0:
                break
            take_count = min(needed_students, len(cand["free_pcs"]))
            taken_pcs = cand["free_pcs"][:take_count]
            allocated_pcs.extend(taken_pcs)
            needed_students -= take_count

            spare_count = len(cand["free_pcs"]) - take_count
            lab_allocation_summary.append({
                "lab_id": cand["lab"]["id"],
                "lab_name": cand["lab"]["name"],
                "allocated_students": take_count,
                "spare_pcs_available_for_others": spare_count
            })

    # 4. Atomic Commit: Create reservations for the allocated workstations
    now = datetime.now(timezone.utc)
    is_immediate = (now >= (req.start_time - timedelta(minutes=10)) and now <= req.end_time)
    initial_status = 'HELD' if is_immediate else 'PENDING'

    created_reservation_ids = []
    for pc in allocated_pcs:
        r_id = await fetch_val("""
            INSERT INTO reservations (
                student_id, pc_id, task_type, batch_name, time_range, status, notes
            ) VALUES (
                $1, $2, 'Coursework', $3, tstzrange($4, $5, '[)'), $6, $7
            ) RETURNING id;
        """, user_id, pc["id"], req.batch_name, req.start_time, req.end_time,
             initial_status, f"Faculty Extra Lab: {req.course_name} ({req.batch_name})")
        created_reservation_ids.append(r_id)

    # Flip PC state if immediate
    if is_immediate:
        for pc in allocated_pcs:
            await execute("UPDATE pcs SET state = 'HELD', updated_at = CURRENT_TIMESTAMP WHERE id = $1 AND state != 'OCCUPIED' AND state != 'MAINTENANCE'", pc["id"])

    return {
        "status": "success",
        "course_name": req.course_name,
        "batch_name": req.batch_name,
        "allocation_strategy": strategy,
        "total_students_seated": len(allocated_pcs),
        "lab_partition_plan": lab_allocation_summary,
        "message": f"Successfully reserved extra lab for {req.batch_name} ({len(allocated_pcs)} students) via {strategy} strategy across {len(lab_allocation_summary)} lab(s)."
    }

@router.get("/my-sessions")
async def get_my_faculty_sessions(payload: dict = Depends(get_current_user_token_payload)):
    from backend.app.core.lifecycle import reap_expired_allocations
    await reap_expired_allocations()
    user_id = int(payload["sub"])
    role = payload.get("role", "student")

    # Faculty or Admin can view their cohort reservations aggregated by batch and time range
    sessions = await fetch_all("""
        SELECT r.batch_name,
               MIN(r.notes) as notes,
               CASE 
                   WHEN bool_or(r.status = 'ACTIVE') THEN 'ACTIVE'
                   WHEN bool_or(r.status = 'HELD') THEN 'HELD'
                   WHEN bool_or(r.status = 'PENDING') THEN 'PENDING'
                   WHEN bool_or(r.status = 'COMPLETED') THEN 'COMPLETED'
                   ELSE 'CANCELLED'
               END as status,
               MIN(lower(r.time_range)) as start_time,
               MAX(upper(r.time_range)) as end_time,
               COUNT(DISTINCT r.id) as workstation_count,
               array_agg(DISTINCT l.name) as labs_involved,
               MAX(r.created_at) as created_at
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        JOIN labs l ON l.id = p.lab_id
        WHERE (r.student_id = $1 OR $2 = 'admin') AND r.batch_name IS NOT NULL
        GROUP BY r.batch_name, date_trunc('minute', lower(r.time_range)), date_trunc('minute', upper(r.time_range))
        ORDER BY MAX(r.created_at) DESC
        LIMIT 20;
    """, user_id, role)
    return sessions

@router.post("/sessions/end")
async def end_faculty_session(
    req: EndFacultySessionRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Immediately concludes an extra practical lab session:
    - Marks all reservations for the specified batch as COMPLETED
    - Closes any active student sessions for this batch
    - Instantly restores all assigned workstations back to AVAILABLE
    """
    user_id = int(payload["sub"])
    role = payload.get("role", "student")

    if role not in ("faculty", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only faculty members and administrators can end lab sessions."
        )

    res_records = await fetch_all("""
        SELECT id, pc_id
        FROM reservations
        WHERE batch_name = $1
          AND status IN ('PENDING', 'HELD', 'ACTIVE')
          AND ($2 = 'admin' OR student_id = $3);
    """, req.batch_name, role, user_id)

    if not res_records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active or pending lab session found for batch '{req.batch_name}'"
        )

    res_ids = [r["id"] for r in res_records]
    pc_ids = [r["pc_id"] for r in res_records]

    await execute("""
        UPDATE reservations
        SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
        WHERE id = ANY($1::int[]);
    """, res_ids)

    await execute("""
        UPDATE sessions
        SET status = 'CLOSED', end_time = CURRENT_TIMESTAMP, close_reason = 'Faculty Concluded Lab Session'
        WHERE reservation_id = ANY($1::int[]) AND status = 'ACTIVE';
    """, res_ids)

    await execute("""
        UPDATE pcs
        SET state = 'AVAILABLE', updated_at = CURRENT_TIMESTAMP
        WHERE id = ANY($1::int[]) AND state != 'MAINTENANCE';
    """, pc_ids)

    return {
        "status": "success",
        "batch_name": req.batch_name,
        "workstations_freed": len(pc_ids),
        "message": f"Lab session for '{req.batch_name}' ended. {len(pc_ids)} workstations restored to AVAILABLE."
    }
