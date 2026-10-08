import pytest
import os
import shutil
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from backend.app.main import app
from agent.labtrack_agent import WorkstationAgent

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client

def test_01_workstation_boots_available(client):
    """1. Verify Workstation boots into AVAILABLE state."""
    resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["hostname"] == "COMP-PC-01"
    assert data["state"] == "AVAILABLE"
    assert "Walk-in Permitted" in data["message"]

def test_02_advance_booking_flips_pc_to_held(client):
    """2. Advance booking flips PC state to HELD with student metadata."""
    # Authenticate as STU001 (Alice Johnson)
    login_resp = client.post("/api/auth/login", json={"roll_no": "STU001", "password": "stu123"})
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch PC id for COMP-PC-01
    pc_resp = client.get("/api/pcs")
    comp1 = next(p for p in pc_resp.json() if p["hostname"] == "COMP-PC-01")

    # Reserve starting now to trigger immediate HELD state
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(minutes=2)
    end_time = now + timedelta(hours=2)

    book_resp = client.post(
        "/api/reservations/advance",
        json={
            "pc_id": comp1["id"],
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "task_type": "Senior Project",
            "software_required": ["MATLAB"]
        },
        headers=headers
    )
    assert book_resp.status_code == 200, book_resp.text
    booking = book_resp.json()["reservation"]
    assert booking["hostname"] == "COMP-PC-01"

    # Verify PC lock-state has flipped to HELD with student metadata
    lock_resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert lock_resp.status_code == 200
    lock_data = lock_resp.json()
    assert lock_data["state"] == "HELD"
    assert lock_data["reserved_student_name"] == "Alice Johnson"
    assert lock_data["reserved_roll_no"] == "STU001"
    assert lock_data["remaining_grace_seconds"] is not None
    assert lock_data["remaining_grace_seconds"] > 0

def test_03_unauthorized_student_rejected_403(client):
    """3. Unauthorized student attempting login on a HELD PC is rejected (403 Forbidden)."""
    # STU002 (Bob Smith) attempts to unlock COMP-PC-01 which is reserved for STU001
    checkin_resp = client.post(
        "/api/agent/checkin",
        json={
            "hostname": "COMP-PC-01",
            "roll_no": "STU002",
            "password": "stu123",
            "cgroup_path": "/sys/fs/cgroup/labtrack/session_STU002",
            "workspace_path": "/tmp/labtrack/workspace_STU002"
        }
    )
    assert checkin_resp.status_code == 403
    err_detail = checkin_resp.json()["detail"]
    assert "Access Denied: Workstation reserved for Alice Johnson" in err_detail

def test_04_reserved_student_unlocks_and_initializes_telemetry(client):
    """4. Reserved student logs in successfully, unlocking the machine and initializing telemetry."""
    # STU001 (Alice Johnson) authenticates on COMP-PC-01
    checkin_resp = client.post(
        "/api/agent/checkin",
        json={
            "hostname": "COMP-PC-01",
            "roll_no": "STU001",
            "password": "stu123",
            "cgroup_path": "/sys/fs/cgroup/labtrack/session_STU001",
            "workspace_path": "/tmp/labtrack/workspace_STU001"
        }
    )
    assert checkin_resp.status_code == 200, checkin_resp.text
    session_data = checkin_resp.json()
    assert session_data["status"] == "UNLOCKED"
    session_id = session_data["session_id"]
    assert session_id > 0

    # Verify PC lock state is now OCCUPIED
    lock_resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert lock_resp.status_code == 200
    lock_data = lock_resp.json()
    assert lock_data["state"] == "OCCUPIED"
    assert lock_data["active_session"]["student_name"] == "Alice Johnson"

    # Ingest telemetry sample
    telem_resp = client.post(
        "/api/agent/telemetry",
        json={
            "session_id": session_id,
            "hostname": "COMP-PC-01",
            "cpu_percent": 14.5,
            "memory_rss_bytes": 1073741824,
            "memory_percent": 12.8,
            "page_faults": 450,
            "process_count": 82,
            "load_average": 0.35
        }
    )
    assert telem_resp.status_code == 200
    assert telem_resp.json()["status"] == "recorded"

    # Save session_id for test 05
    pytest.shared_session_id = session_id

def test_05_student_logout_restores_available(client):
    """5. Student logout releases resources, re-locks the PC, and restores it to AVAILABLE."""
    session_id = getattr(pytest, "shared_session_id", 1)

    close_resp = client.post(
        "/api/agent/close",
        json={
            "session_id": session_id,
            "reason": "Student completed lab practice"
        }
    )
    assert close_resp.status_code == 200, close_resp.text
    assert close_resp.json()["status"] == "closed"

    # Verify PC lock-state has returned to AVAILABLE
    lock_resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert lock_resp.status_code == 200
    lock_data = lock_resp.json()
    assert lock_data["state"] == "AVAILABLE"
    assert "Walk-in Permitted" in lock_data["message"]

def test_06_research_paper_ga_simulation(client):
    """6. Call POST /api/scheduler/simulate-comparison and verify GA results demonstrate +16.3% to +34.6% gains."""
    sim_resp = client.post("/api/scheduler/simulate-comparison")
    assert sim_resp.status_code == 200, sim_resp.text
    data = sim_resp.json()

    assert data["status"] == "success"
    utilization = data["equipment_utilization"]

    # Utilization improvement check: +16.3% to +34.6%
    gain = utilization["absolute_gain_pct"]
    assert 16.0 <= gain <= 35.0, f"Expected gain in +16.3% to +34.6%, got {gain}%"

    # GA Convergence check
    convergence = data["fitness_convergence"]
    assert len(convergence) >= 20
    # First gen fitness should be lower than final converged fitness
    assert convergence[-1] >= convergence[0]

    # Hard constraints M1 - M6 check
    hard_m = data["hard_constraints_satisfied"]
    assert hard_m["M1_student_no_conflict"] is True
    assert hard_m["M2_instructor_no_conflict"] is True
    assert hard_m["M3_course_coverage"] is True
    assert hard_m["M4_cohort_co_scheduling"] is True
    assert hard_m["M5_lab_capacity_compliance"] is True
    assert hard_m["M6_instructor_availability"] is True

    # TaskPool Queue verification
    queue = data["taskpool_queue"]
    assert len(queue) > 0
    # Dynamic aging score P_task calculation
    assert "p_task" in queue[0]
    assert queue[0]["p_task"] > 0

def test_07_agent_daemon_sandbox_and_hygiene_wipe():
    """7. Verify Agent Daemon workspace sandbox creation and post-session wipe."""
    agent = WorkstationAgent()
    session_id = 9999

    # Setup workspace
    workspace = agent.setup_workspace_sandbox(session_id)
    assert os.path.exists(workspace)
    assert os.path.isdir(workspace)

    # Write a test student file
    test_file = os.path.join(workspace, "student_lab_code.py")
    with open(test_file, "w") as f:
        f.write("print('lab code')")
    assert os.path.exists(test_file)

    # Teardown & wipe
    agent.wipe_workspace_sandbox()
    assert not os.path.exists(workspace), "Workspace directory must be wiped after logout"
