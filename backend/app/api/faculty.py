from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, date
from pydantic import BaseModel
import asyncpg
from backend.app.core.security import get_current_user_token_payload
from backend.app.core.database import fetch_all, fetch_one, execute, fetch_val

router = APIRouter(prefix="/faculty", tags=["Faculty Operations"])

class ExtraLabReservationRequest(BaseModel):
    course_name: str
    batch_name: str  # e.g., "3rd Year CSE - Section A"
    student_count: int  # e.g., 107
    preferred_lab_id: Optional[int] = 1
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = "Extra practical / makeup lab session"

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
          AND DATE(lower(r.time_range)) = DATE($2::timestamptz)
        LIMIT 1;
    """, req.batch_name, req.start_time)

    if same_day_conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Constraint M1 Violation: Batch '{req.batch_name}' already has a practical lab scheduled "
                f"on {req.start_time.strftime('%Y-%m-%d')} ({same_day_conflict['lab_name']} at {same_day_conflict['start_time'].strftime('%H:%M')}). "
                "Indian college policy strictly caps students at at most 1 practical lab per day."
            )
        )

    # 2. Constraint M2: Requesting Faculty Clash Prevention
    # Check if this faculty is already booking another lab simultaneously
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

    needed_students = req.student_count
    allocated_pcs = []
    lab_allocation_summary = []

    for lab in labs:
        if needed_students <= 0:
            break

        # Query available PCs in this lab that do not have overlapping bookings
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

        if not free_pcs_in_lab:
            continue

        take_count = min(needed_students, len(free_pcs_in_lab))
        taken_pcs = free_pcs_in_lab[:take_count]
        allocated_pcs.extend(taken_pcs)
        needed_students -= take_count

        spare_count = len(free_pcs_in_lab) - take_count
        lab_allocation_summary.append({
            "lab_id": lab["id"],
            "lab_name": lab["name"],
            "allocated_students": take_count,
            "spare_pcs_available_for_others": spare_count
        })

    if needed_students > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Insufficient lab capacity across all labs. Needed {req.student_count} workstations, "
                f"but only {len(allocated_pcs)} clash-free workstations are available for this time slot."
            )
        )

    # 4. Atomic Commit: Create reservations for the allocated workstations
    now = datetime.now(timezone.utc)
    is_immediate = (now >= req.start_time and now <= req.end_time)
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
            await execute("UPDATE pcs SET state = 'HELD', updated_at = CURRENT_TIMESTAMP WHERE id = $1", pc["id"])

    return {
        "status": "success",
        "course_name": req.course_name,
        "batch_name": req.batch_name,
        "total_students_seated": len(allocated_pcs),
        "lab_partition_plan": lab_allocation_summary,
        "message": f"Successfully reserved extra lab for {req.batch_name} ({len(allocated_pcs)} students) across {len(lab_allocation_summary)} lab(s)."
    }
