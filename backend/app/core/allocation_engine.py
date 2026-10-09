"""
LabTrack Priority and Task-Based Allocation Engine
Implementation of Section 6 from Operating Systems Project Proposal:
- Priority hierarchy (Faculty/Exam > Senior Project > Coursework > Practice > Walk-in)
- Dynamic Priority Aging based on wait time and approaching deadlines
- Task-to-Lab matching:
    * Practice -> Computing Lab (Lab 1)
    * Intensive builds & dev -> Software Engineering Lab (Lab 2)
    * Specific licensed software (MATLAB, Vivado, AutoCAD) & GPU -> Licensed PCs / AI Lab (Lab 3)
- Overflow Rule: Small tasks only use Software Engineering Lab when Computing Lab is full and spare capacity exists.
- Software license semaphore validation.
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
import math
from backend.app.core.database import fetch_all, fetch_one, fetch_val

# Priority Base Weights from Section 6
PRIORITY_WEIGHTS = {
    "Exam": 100,
    "Faculty": 100,
    "Senior Project": 80,
    "Coursework": 50,
    "Practice": 20,
    "Walk-in": 5
}

def calculate_priority_score(
    role: str,
    task_type: str,
    deadline: Optional[datetime] = None,
    created_at: Optional[datetime] = None
) -> Tuple[int, str]:
    """
    Computes static priority and dynamic aging score:
    P_dynamic = P_base * (1 + wait_time_min / max(minutes_to_deadline, 1))
    """
    now = datetime.now(timezone.utc)
    
    # 1. Determine Base Priority
    if role == "faculty" or task_type == "Exam":
        base = PRIORITY_WEIGHTS["Exam"]
        label = "Highest: Faculty / Exam Block"
    elif task_type == "Senior Project":
        base = PRIORITY_WEIGHTS["Senior Project"]
        label = "High: Senior Capstone Project"
    elif task_type == "Coursework":
        base = PRIORITY_WEIGHTS["Coursework"]
        label = "Medium: Coursework & Assignments"
    elif task_type == "Walk-in":
        base = PRIORITY_WEIGHTS["Walk-in"]
        label = "Lowest: Walk-in Session"
    else:
        base = PRIORITY_WEIGHTS.get(task_type, 20)
        label = "Low: Regular Lab Practice"

    # 2. Dynamic Aging based on Wait Time & Approaching Deadline
    wait_minutes = 0.0
    if created_at:
        wait_minutes = max(0.0, (now - created_at).total_seconds() / 60.0)

    aging_factor = 1.0
    if deadline:
        # Time remaining until deadline
        diff_sec = (deadline - now).total_seconds()
        min_to_deadline = max(1.0, diff_sec / 60.0)
        # Closer deadline + longer wait -> sharp priority increase
        aging_factor = 1.0 + (wait_minutes / min_to_deadline) * 10.0
    elif wait_minutes > 0:
        # Moderate wait-time aging if no explicit deadline (prevent starvation)
        aging_factor = 1.0 + (wait_minutes / 120.0)

    score = int(round(base * aging_factor))
    return score, label

async def check_software_licenses(software_required: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Validates counting semaphores for requested commercial software licenses.
    """
    for sw_name in software_required:
        if sw_name == "PyTorch GPU":
            continue
        lic = await fetch_one("""
            SELECT s.name, l.active_seats, l.max_seats
            FROM software s
            JOIN licenses l ON l.software_id = s.id
            WHERE s.name = $1
        """, sw_name)
        if lic:
            if lic["active_seats"] >= lic["max_seats"]:
                return False, f"License semaphore exhausted for {sw_name}: all {lic['max_seats']} seats currently occupied."
    return True, None

async def allocate_workstation_for_request(
    student_id: int,
    role: str,
    task_type: str,
    software_required: List[str],
    start_time: datetime,
    end_time: datetime,
    target_pc_id: Optional[int] = None,
    requested_lab_id: Optional[int] = None,
    deadline: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Executes Proposal Section 6 allocation logic:
    1. If target_pc_id specified directly, validates availability.
    2. Enforces software license semaphores.
    3. Matches task to ideal lab:
       - Practice/Coursework -> Lab 1 (Computing Lab)
       - Senior Project/Builds/Intensive -> Lab 2 (Software Engineering Lab)
       - PyTorch GPU -> Lab 3 (AI Lab)
    4. Enforces Overflow Rule:
       - Practice task uses Lab 2 ONLY IF Lab 1 is 100% full AND Lab 2 has spare capacity.
    5. Applies dynamic priority scoring.
    """
    # 1. License Check
    lic_ok, lic_err = await check_software_licenses(software_required)
    if not lic_ok:
        return {
            "success": False,
            "error_type": "LICENSE_EXHAUSTED",
            "message": lic_err
        }

    # 2. Priority Calculation
    priority_score, priority_label = calculate_priority_score(
        role=role,
        task_type=task_type,
        deadline=deadline
    )

    # 3. Direct PC specification
    if target_pc_id:
        pc = await fetch_one("""
            SELECT p.id, p.hostname, p.lab_id, l.name as lab_name, l.has_gpu, p.state
            FROM pcs p
            JOIN labs l ON l.id = p.lab_id
            WHERE p.id = $1 AND p.state != 'MAINTENANCE'
        """, target_pc_id)
        if not pc:
            return {"success": False, "error_type": "PC_NOT_FOUND", "message": "Specified workstation not found or in maintenance."}

        # Check collision
        collision = await fetch_one("""
            SELECT 1 FROM reservations r
            WHERE r.pc_id = $1
              AND r.status IN ('PENDING', 'HELD', 'ACTIVE')
              AND r.time_range && tstzrange($2, $3, '[)')
        """, target_pc_id, start_time, end_time)
        if collision:
            return {"success": False, "error_type": "TIME_CONFLICT", "message": f"{pc['hostname']} is already reserved during this time slot."}

        return {
            "success": True,
            "pc_id": pc["id"],
            "hostname": pc["hostname"],
            "lab_id": pc["lab_id"],
            "lab_name": pc["lab_name"],
            "priority_score": priority_score,
            "allocation_basis": f"Direct user selection: {pc['hostname']} in {pc['lab_name']}",
            "overflow_applied": False
        }

    # 4. Automated Task-to-Lab Matching
    needs_gpu = "PyTorch GPU" in software_required
    needs_matlab = "MATLAB" in software_required
    needs_vivado = "Vivado" in software_required
    needs_autocad = "AutoCAD" in software_required

    # Determine Ideal Lab
    if needs_gpu:
        ideal_lab_id = 3  # AI & High-Performance Lab (RTX 4090)
        allocation_reason = "Matched to Lab 3 (AI Lab): PyTorch GPU & High-VRAM requirement"
    elif needs_vivado or needs_autocad:
        ideal_lab_id = 2  # Software Engineering Lab
        allocation_reason = "Matched to Lab 2 (Software Eng Lab): Specialized engineering software (Vivado/AutoCAD)"
    elif task_type in ("Senior Project", "Exam") or (requested_lab_id == 2):
        ideal_lab_id = 2  # Software Engineering Lab
        allocation_reason = "Matched to Lab 2 (Software Eng Lab): High-capacity CPU & dev builds for Senior Project"
    else:
        # Default for Practice and regular Coursework
        ideal_lab_id = 1  # Computing Lab
        allocation_reason = "Matched to Lab 1 (Computing Lab): Light requirements; keeps high-capacity machines free"

    # Allow user explicit lab request if no conflicting hardware/software requirement
    target_lab_id = requested_lab_id if (requested_lab_id and not needs_gpu) else ideal_lab_id

    # 5. Helper to query free PCs in a lab
    async def get_free_pcs(l_id: int):
        return await fetch_all("""
            SELECT p.id, p.hostname, p.lab_id, l.name as lab_name
            FROM pcs p
            JOIN labs l ON l.id = p.lab_id
            WHERE p.lab_id = $1
              AND p.state != 'MAINTENANCE'
              AND NOT EXISTS (
                  SELECT 1 FROM reservations r
                  WHERE r.pc_id = p.id
                    AND r.status IN ('PENDING', 'HELD', 'ACTIVE')
                    AND r.time_range && tstzrange($2, $3, '[)')
              )
            ORDER BY p.hostname ASC
        """, l_id, start_time, end_time)

    free_pcs = await get_free_pcs(target_lab_id)

    overflow_applied = False
    chosen_pc = None

    if free_pcs:
        chosen_pc = free_pcs[0]
        final_basis = allocation_reason
    else:
        # 6. Apply Section 6 Overflow Rule:
        # "Small tasks use the Software Engineering Lab only when the Computing Lab is full and spare capacity exists."
        if target_lab_id == 1 and not needs_gpu:
            # Check spare capacity in Lab 2
            lab2_free = await get_free_pcs(2)
            # Spare capacity threshold: at least 2 free PCs in Lab 2
            if len(lab2_free) >= 2:
                chosen_pc = lab2_free[0]
                overflow_applied = True
                final_basis = (
                    "Section 6 Overflow Rule Applied: Computing Lab (Lab 1) is 100% full. "
                    f"Allocated spare capacity in Software Engineering Lab ({chosen_pc['hostname']})."
                )
            else:
                return {
                    "success": False,
                    "error_type": "NO_CAPACITY_OVERFLOW_DENIED",
                    "message": (
                        "Computing Lab (Lab 1) is fully booked for this time window. "
                        "Overflow into Software Engineering Lab was denied to preserve capacity for project/exam work."
                    )
                }
        else:
            return {
                "success": False,
                "error_type": "LAB_CAPACITY_FULL",
                "message": f"No available workstations matching requirements in selected lab for the requested time window."
            }

    return {
        "success": True,
        "pc_id": chosen_pc["id"],
        "hostname": chosen_pc["hostname"],
        "lab_id": chosen_pc["lab_id"],
        "lab_name": chosen_pc["lab_name"],
        "priority_score": priority_score,
        "priority_label": priority_label,
        "allocation_basis": final_basis,
        "overflow_applied": overflow_applied
    }
