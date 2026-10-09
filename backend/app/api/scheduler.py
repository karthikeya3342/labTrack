from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from backend.app.core.intelligent_scheduler import run_simulation_comparison, DynamicTaskPoolScheduler, TaskPoolItem
from backend.app.core.security import get_current_user_token_payload
from backend.app.core.database import fetch_all, fetch_one, execute, fetch_val

router = APIRouter(prefix="/scheduler", tags=["Intelligent Scheduler"])

class WaitlistJoinRequest(BaseModel):
    task_type: str = "Practice"
    software_required: Optional[List[str]] = []
    target_lab_id: Optional[int] = None
    deadline: Optional[datetime] = None

@router.post("/simulate-comparison")
async def simulate_scheduler_comparison():
    """
    Simulates laboratory scheduling comparing:
    - Baseline FCFS
    - Intelligent Heuristic GA (VPPM from Chao He & Shi Cheng 2025)
    Returns equipment utilization improvements (+16.3% to +34.6%), GA convergence, Gantt chart, and TaskPool items.
    """
    result = run_simulation_comparison()
    return result

@router.get("/taskpool")
async def get_dynamic_taskpool():
    """Returns static GA simulation task pool preview."""
    pool = DynamicTaskPoolScheduler()
    sample_tasks = [
        TaskPoolItem("TASK-101", "STU001", "Alice Johnson", "Senior Project", 120.0, 1, 32.0, 8, waiting_time_min=45.0, running_time_min=75.0, is_running=True, assigned_lab_id=3, assigned_pc="AI-PC-01"),
        TaskPoolItem("TASK-102", "STU002", "Bob Smith", "Practice", 60.0, 0, 16.0, 4, waiting_time_min=15.0, running_time_min=30.0, is_running=True, assigned_lab_id=1, assigned_pc="COMP-PC-03"),
        TaskPoolItem("TASK-103", "STU003", "Charlie Brown", "Exam", 90.0, 1, 48.0, 12, waiting_time_min=80.0, running_time_min=0.0, is_running=False),
        TaskPoolItem("TASK-104", "STU004", "Diana Prince", "Coursework", 45.0, 0, 16.0, 4, waiting_time_min=10.0, running_time_min=0.0, is_running=False),
        TaskPoolItem("TASK-105", "STU005", "Ethan Hunt", "Research Experiment", 180.0, 2, 64.0, 16, waiting_time_min=110.0, running_time_min=0.0, is_running=False)
    ]
    for t in sample_tasks:
        pool.add_task(t)
    return pool.get_ranked_queue()

# -------------------------------------------------------------
# Dynamic Real TaskPool Waitlist & Auto-Promotion Engine
# -------------------------------------------------------------

@router.post("/waitlist/join")
async def join_waitlist(
    req: WaitlistJoinRequest,
    payload: dict = Depends(get_current_user_token_payload)
):
    """
    Adds a student to the real dynamic TaskPool waitlist when all candidate workstations are full.
    Enforces Priority Hierarchy and aging formula from Proposal Section 6 & Paper Section 2.3.
    """
    student_id = int(payload["sub"])
    role = payload.get("role", "student")

    # Priority mapping
    base_scores = {
        "Faculty": 100,
        "Senior Project": 80,
        "Coursework": 50,
        "Practice": 20,
        "Walk-in": 5,
        "Exam": 95
    }
    p_base = 100 if role in ("faculty", "admin") else base_scores.get(req.task_type, 20)

    now = datetime.now(timezone.utc)
    if req.deadline:
        hours_until = (req.deadline - now).total_seconds() / 3600.0
        if 0 < hours_until <= 24:
            p_base += 15

    # Check if student already has a QUEUED waitlist entry
    existing = await fetch_one("""
        SELECT id FROM taskpool_entries
        WHERE student_id = $1 AND status = 'QUEUED'
    """, student_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active entry in the TaskPool waitlist."
        )

    entry_id = await fetch_val("""
        INSERT INTO taskpool_entries (
            student_id, task_type, software_required, target_lab_id, deadline,
            wait_start_time, current_priority, status
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, 'QUEUED'
        ) RETURNING id;
    """, student_id, req.task_type, req.software_required or [], req.target_lab_id, req.deadline, now, float(p_base))

    return {
        "status": "queued",
        "entry_id": entry_id,
        "base_priority": p_base,
        "message": f"Successfully joined TaskPool waitlist with initial priority score {p_base}."
    }

@router.get("/waitlist")
async def get_real_waitlist():
    """
    Returns all QUEUED students in the real TaskPool, dynamically recalculating aging bonuses:
    P_dynamic = P_base + min(30, wait_minutes * 0.5)
    """
    now = datetime.now(timezone.utc)
    entries = await fetch_all("""
        SELECT t.id, t.student_id, u.name as student_name, u.roll_no,
               t.task_type, t.software_required, t.target_lab_id, l.name as lab_name,
               t.deadline, t.wait_start_time, t.current_priority, t.status, t.created_at
        FROM taskpool_entries t
        JOIN users u ON u.id = t.student_id
        LEFT JOIN labs l ON l.id = t.target_lab_id
        WHERE t.status = 'QUEUED'
        ORDER BY t.wait_start_time ASC;
    """)

    ranked = []
    for e in entries:
        wait_seconds = (now - e["wait_start_time"]).total_seconds()
        wait_minutes = max(0.0, wait_seconds / 60.0)
        aging_bonus = min(30.0, wait_minutes * 0.5)

        base_priority = float(e["current_priority"])
        dynamic_score = round(base_priority + aging_bonus, 1)

        # Update dynamic priority in DB
        await execute("UPDATE taskpool_entries SET current_priority = $1 WHERE id = $2", dynamic_score, e["id"])

        ranked.append({
            "id": e["id"],
            "student_id": e["student_id"],
            "student_name": e["student_name"],
            "roll_no": e["roll_no"],
            "task_type": e["task_type"],
            "software_required": e["software_required"],
            "target_lab_id": e["target_lab_id"],
            "lab_name": e["lab_name"] or "Any Available Lab",
            "deadline": e["deadline"],
            "wait_minutes": round(wait_minutes, 1),
            "aging_bonus": round(aging_bonus, 1),
            "dynamic_priority": dynamic_score,
            "status": e["status"],
            "created_at": e["created_at"]
        })

    ranked.sort(key=lambda x: x["dynamic_priority"], reverse=True)
    return ranked

@router.delete("/waitlist/{entry_id}")
async def cancel_waitlist_entry(
    entry_id: int,
    payload: dict = Depends(get_current_user_token_payload)
):
    user_id = int(payload["sub"])
    role = payload.get("role", "student")

    entry = await fetch_one("SELECT id, student_id, status FROM taskpool_entries WHERE id = $1", entry_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Waitlist entry not found")
    if role != "admin" and entry["student_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot cancel another student's waitlist entry")

    await execute("UPDATE taskpool_entries SET status = 'CANCELLED' WHERE id = $1", entry_id)
    return {"status": "cancelled", "entry_id": entry_id}

async def promote_next_taskpool_entry(pc_id: int, lab_id: int) -> Optional[Dict[str, Any]]:
    """
    Triggered when a workstation session closes.
    Checks if any students are queued in the TaskPool for this lab.
    Promotes the highest aged-priority candidate, holds the PC in 'HELD' state with 15-min grace.
    """
    now = datetime.now(timezone.utc)
    grace_deadline = now + timedelta(minutes=15)
    end_time = now + timedelta(hours=2)

    # Find highest priority queued entry matching this lab
    candidate = await fetch_one("""
        SELECT t.id, t.student_id, t.task_type, t.software_required, t.current_priority,
               u.name as student_name, u.roll_no
        FROM taskpool_entries t
        JOIN users u ON u.id = t.student_id
        WHERE t.status = 'QUEUED'
          AND (t.target_lab_id IS NULL OR t.target_lab_id = $1)
        ORDER BY t.current_priority DESC, t.wait_start_time ASC
        LIMIT 1;
    """, lab_id)

    if not candidate:
        return None

    # Admit reservation
    res_id = await fetch_val("""
        INSERT INTO reservations (
            student_id, pc_id, task_type, software_required, time_range, status,
            grace_deadline, priority_score, allocation_basis
        ) VALUES (
            $1, $2, $3, $4, tstzrange($5, $6, '[)'), 'HELD', $7, $8, $9
        ) RETURNING id;
    """, candidate["student_id"], pc_id, candidate["task_type"], candidate["software_required"] or [],
         now, end_time, grace_deadline, int(candidate["current_priority"]), "TaskPool Waitlist Dynamic Promotion")

    # Update PC state to HELD
    await execute("UPDATE pcs SET state = 'HELD', updated_at = CURRENT_TIMESTAMP WHERE id = $1", pc_id)

    # Update TaskPool Entry to PROMOTED
    await execute("""
        UPDATE taskpool_entries
        SET status = 'PROMOTED', assigned_pc_id = $1, assigned_reservation_id = $2
        WHERE id = $3;
    """, pc_id, res_id, candidate["id"])

    # Audit log
    await execute("""
        INSERT INTO audit_logs (event_type, user_id, pc_id, details)
        VALUES ('TASKPOOL_PROMOTION', $1, $2, $3::jsonb);
    """, candidate["student_id"], pc_id, f'{{"entry_id": {candidate["id"]}, "reservation_id": {res_id}}}')

    return {
        "entry_id": candidate["id"],
        "student_name": candidate["student_name"],
        "roll_no": candidate["roll_no"],
        "reservation_id": res_id,
        "priority_score": candidate["current_priority"],
        "grace_deadline": grace_deadline.isoformat()
    }
