from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import asyncpg
from backend.app.models.schemas import AdvanceBookingRequest
from backend.app.core.security import get_current_user_token_payload
from backend.app.core.database import fetch_all, fetch_one, fetch_val, execute

from backend.app.core.allocation_engine import allocate_workstation_for_request

router = APIRouter(prefix="/reservations", tags=["Reservations"])

@router.post("/advance")
async def create_advance_booking(
    req: AdvanceBookingRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    student_id = int(payload["sub"])
    role = payload.get("role", "student")
    if role == "faculty":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Faculty members cannot book individual workstations. Please use the Faculty Extra Labs portal (/api/faculty/reserve-extra-lab) to schedule cohort lab sessions."
        )
    if role not in ("student", "admin", "club_lead"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students can book individual workstation reservations.")

    # Proposal Section 6: Priority and Task-Based Allocation
    alloc = await allocate_workstation_for_request(
        student_id=student_id,
        role=role,
        task_type=req.task_type,
        software_required=req.software_required,
        start_time=req.start_time,
        end_time=req.end_time,
        target_pc_id=req.pc_id,
        requested_lab_id=req.lab_id,
        deadline=req.deadline
    )

    if not alloc["success"]:
        err_type = alloc.get("error_type", "CONFLICT")
        status_code = status.HTTP_409_CONFLICT if "FULL" in err_type or "CONFLICT" in err_type or "DENIED" in err_type else status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=status_code,
            detail=alloc["message"]
        )

    target_pc_id = alloc["pc_id"]
    priority_score = alloc["priority_score"]
    allocation_basis = alloc["allocation_basis"]

    try:
        res_id = await fetch_val(
            "SELECT fn_admit_reservation($1, $2, $3, $4, $5, $6, $7, $8, $9);",
            student_id,
            target_pc_id,
            req.start_time,
            req.end_time,
            req.task_type,
            req.software_required,
            priority_score,
            allocation_basis,
            req.deadline
        )
    except (asyncpg.exceptions.IntegrityConstraintViolationError, asyncpg.exceptions.UniqueViolationError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workstation is already booked for an overlapping time window."
        )
    except (asyncpg.exceptions.RaiseError, asyncpg.exceptions.PostgresError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    if req.notes:
        await execute("UPDATE reservations SET notes = $1 WHERE id = $2;", req.notes, res_id)

    # Fetch confirmed booking details with clean purpose and metadata
    booking = await fetch_one("""
        SELECT r.id, r.pc_id, p.hostname, l.name as lab_name,
               lower(r.time_range) as start_time,
               upper(r.time_range) as end_time,
               r.status, r.task_type, r.software_required, r.grace_deadline,
               COALESCE(r.notes, r.task_type) as purpose,
               r.priority_score, r.allocation_basis, r.deadline
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        JOIN labs l ON l.id = p.lab_id
        WHERE r.id = $1
    """, res_id)

    return {
        "status": "success",
        "reservation": booking,
        "allocation": {
            "priority_score": priority_score,
            "allocation_basis": allocation_basis,
            "overflow_applied": alloc.get("overflow_applied", False)
        }
    }

@router.get("/my")
async def get_my_reservations(payload: dict = Depends(get_current_user_token_payload)):
    from backend.app.core.lifecycle import reap_expired_allocations
    await reap_expired_allocations()
    user_id = int(payload["sub"])
    role = payload.get("role", "student")
    if role == "faculty":
        return []
    reservations = await fetch_all("""
        SELECT r.id, r.pc_id, p.hostname, l.name as lab_name,
               lower(r.time_range) as start_time,
               upper(r.time_range) as end_time,
               r.status, r.task_type, r.software_required, r.grace_deadline,
               COALESCE(r.notes, r.task_type) as purpose,
               r.notes, r.created_at
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        JOIN labs l ON l.id = p.lab_id
        WHERE r.student_id = $1 AND r.club_event_id IS NULL AND r.batch_name IS NULL
        ORDER BY r.created_at DESC
        LIMIT 50
    """, user_id)
    return reservations

@router.delete("/{reservation_id}")
async def cancel_reservation(
    reservation_id: int,
    payload: dict = Depends(get_current_user_token_payload)
):
    user_id = int(payload["sub"])
    role = payload.get("role")

    res = await fetch_one("SELECT id, student_id, pc_id, status FROM reservations WHERE id = $1", reservation_id)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    if res["student_id"] != user_id and role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to cancel this reservation")

    await execute("UPDATE reservations SET status = 'CANCELLED' WHERE id = $1", reservation_id)
    # If PC was HELD for this reservation, restore it to AVAILABLE
    if res["status"] == "HELD":
        await execute("UPDATE pcs SET state = 'AVAILABLE' WHERE id = $1 AND state = 'HELD'", res["pc_id"])

    return {"status": "cancelled", "reservation_id": reservation_id}
