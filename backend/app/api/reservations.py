from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import asyncpg
from backend.app.models.schemas import AdvanceBookingRequest
from backend.app.core.security import get_current_user_token_payload
from backend.app.core.database import fetch_all, fetch_one, fetch_val, execute

router = APIRouter(prefix="/reservations", tags=["Reservations"])

@router.post("/advance")
async def create_advance_booking(
    req: AdvanceBookingRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    student_id = int(payload["sub"])
    role = payload.get("role")
    if role not in ("student", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students can book workstation reservations")

    target_pc_id = req.pc_id

    # If no specific PC selected, auto-allocate an available PC in the target lab
    if not target_pc_id and req.lab_id:
        req_gpu = "PyTorch GPU" in req.software_required
        candidate_pcs = await fetch_all("""
            SELECT p.id, p.hostname
            FROM pcs p
            JOIN labs l ON l.id = p.lab_id
            WHERE p.lab_id = $1
              AND p.state != 'MAINTENANCE'
              AND ($2 = FALSE OR l.has_gpu = TRUE)
              AND NOT EXISTS (
                  SELECT 1 FROM reservations r
                  WHERE r.pc_id = p.id
                    AND r.status IN ('PENDING', 'HELD', 'ACTIVE')
                    AND r.time_range && tstzrange($3, $4, '[)')
              )
            ORDER BY p.hostname ASC
            LIMIT 1
        """, req.lab_id, req_gpu, req.start_time, req.end_time)

        if not candidate_pcs:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No available workstation matching requirements in selected lab for this time slot"
            )
        target_pc_id = candidate_pcs[0]["id"]

    if not target_pc_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify either pc_id or lab_id"
        )

    try:
        res_id = await fetch_val(
            "SELECT fn_admit_reservation($1, $2, $3, $4, $5, $6);",
            student_id,
            target_pc_id,
            req.start_time,
            req.end_time,
            req.task_type,
            req.software_required
        )
    except asyncpg.exceptions.ExclusionConstraintViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workstation is already booked for an overlapping time window."
        )
    except (asyncpg.exceptions.RaiseError, asyncpg.exceptions.PostgresError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # Fetch confirmed booking details
    booking = await fetch_one("""
        SELECT r.id, r.pc_id, p.hostname, l.name as lab_name,
               lower(r.time_range) as start_time,
               upper(r.time_range) as end_time,
               r.status, r.task_type, r.software_required, r.grace_deadline
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        JOIN labs l ON l.id = p.lab_id
        WHERE r.id = $1
    """, res_id)

    return {"status": "success", "reservation": booking}

@router.get("/my")
async def get_my_reservations(payload: dict = Depends(get_current_user_token_payload)):
    user_id = int(payload["sub"])
    reservations = await fetch_all("""
        SELECT r.id, r.pc_id, p.hostname, l.name as lab_name,
               lower(r.time_range) as start_time,
               upper(r.time_range) as end_time,
               r.status, r.task_type, r.software_required, r.grace_deadline,
               r.created_at
        FROM reservations r
        JOIN pcs p ON p.id = r.pc_id
        JOIN labs l ON l.id = p.lab_id
        WHERE r.student_id = $1
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
