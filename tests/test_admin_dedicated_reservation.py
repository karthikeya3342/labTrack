import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from backend.app.main import app
import asyncio
from backend.app.core.database import execute, fetch_one

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture(scope="module", autouse=True)
def cleanup_dedicated_reservations(client):
    yield
    admin_token = get_admin_token(client)
    # Master reset to clean up test reservations and restore fleet
    client.post("/api/admin/system/release-all", headers={"Authorization": f"Bearer {admin_token}"})

def get_auth_token(client, roll_no="STU001", password="stu123"):
    resp = client.post("/api/auth/login", json={"roll_no": roll_no, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]

def get_admin_token(client):
    return get_auth_token(client, "admin", "admin123")

def test_1_admin_student_search(client):
    """Admin can search students by roll number or name."""
    admin_token = get_admin_token(client)
    resp = client.get("/api/admin/students/search?q=STU001", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["roll_no"] == "STU001"

    # Non-admin cannot access student search
    stu_token = get_auth_token(client, "STU001", "stu123")
    resp_unauth = client.get("/api/admin/students/search?q=STU", headers={"Authorization": f"Bearer {stu_token}"})
    assert resp_unauth.status_code == 403

def test_2_admin_create_dedicated_reservation(client):
    """Admin creates a dedicated reservation for student STU001 on COMP-PC-01."""
    admin_token = get_admin_token(client)

    # Clean any holds across fleet first using admin endpoint
    client.post("/api/admin/system/release-all", headers={"Authorization": f"Bearer {admin_token}"})

    payload = {
        "student_identifier": "STU001",
        "hostname": "COMP-PC-01",
        "duration_minutes": 60,
        "purpose": "Final Project Defense Evaluation",
        "notes": "Workstation assigned for presentation",
        "force_preempt": False
    }
    resp = client.post("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"}, json=payload)
    assert resp.status_code == 200, f"Dedicated reservation failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "success"
    assert data["hostname"] == "COMP-PC-01"
    assert data["roll_no"] == "STU001"
    assert data["reservation_status"] == "HELD"
    res_id = data["reservation_id"]

    # Verify lock-state of COMP-PC-01
    lock_resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert lock_resp.status_code == 200
    lock_data = lock_resp.json()
    assert lock_data["state"] == "HELD"
    assert lock_data["reserved_roll_no"] == "STU001"
    assert lock_data["is_admin_dedicated"] is True
    assert "Reserved by Admin" in lock_data["message"]

    # Verify listing dedicated reservations
    list_resp = client.get("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"})
    assert list_resp.status_code == 200
    res_list = list_resp.json()
    matched = next((r for r in res_list if r["id"] == res_id), None)
    assert matched is not None
    assert matched["roll_no"] == "STU001"
    assert matched["remaining_seconds"] > 0

def test_3_strict_workstation_lockout_enforcement(client):
    """Unauthorized student (STU002) is denied access; designated student (STU001) successfully logs in."""
    # Attempt login by Bob (STU002) on COMP-PC-01 -> MUST be rejected with 403 Forbidden
    resp_unauth = client.post("/api/agent/checkin", json={
        "hostname": "COMP-PC-01",
        "roll_no": "STU002",
        "password": "stu123"
    })
    assert resp_unauth.status_code == 403
    assert "Access Denied" in resp_unauth.json()["detail"]

    # Attempt login by Alice (STU001) on COMP-PC-01 -> MUST succeed
    resp_auth = client.post("/api/agent/checkin", json={
        "hostname": "COMP-PC-01",
        "roll_no": "STU001",
        "password": "stu123"
    })
    assert resp_auth.status_code == 200
    auth_data = resp_auth.json()
    assert auth_data["status"] == "UNLOCKED"
    assert auth_data["roll_no"] == "STU001"

    # PC state must now be OCCUPIED
    lock_resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert lock_resp.status_code == 200
    assert lock_resp.json()["state"] == "OCCUPIED"

def test_4_dedicated_reservation_preservation_on_logout(client):
    """When the designated student logs out while time remains, PC reverts to HELD (reserved for them)."""
    # STU001 logs out
    close_resp = client.post("/api/agent/close", json={
        "hostname": "COMP-PC-01",
        "reason": "Stepping out for break"
    })
    assert close_resp.status_code == 200

    # PC state must revert to HELD for STU001 (not free to walk-in!)
    lock_resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert lock_resp.status_code == 200
    lock_data = lock_resp.json()
    assert lock_data["state"] == "HELD"
    assert lock_data["reserved_roll_no"] == "STU001"
    assert lock_data["is_admin_dedicated"] is True

def test_5_admin_extend_reservation(client):
    """Admin extends the reservation by +45 minutes."""
    admin_token = get_admin_token(client)

    # Get active dedicated reservation ID
    list_resp = client.get("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"})
    assert list_resp.status_code == 200
    res_list = [r for r in list_resp.json() if r["hostname"] == "COMP-PC-01" and r["status"] in ("HELD", "ACTIVE")]
    assert len(res_list) > 0
    res_id = res_list[0]["id"]
    orig_end = res_list[0]["end_time"]

    # Extend by 45 minutes
    ext_resp = client.post(
        f"/api/admin/reservations/{res_id}/extend",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"additional_minutes": 45}
    )
    assert ext_resp.status_code == 200, f"Extend failed: {ext_resp.text}"
    ext_data = ext_resp.json()
    assert ext_data["status"] == "success"
    assert ext_data["remaining_minutes"] >= 45

def test_6_admin_release_reservation(client):
    """Admin releases reservation early, restoring PC to AVAILABLE walk-in mode."""
    admin_token = get_admin_token(client)

    list_resp = client.get("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"})
    res_list = [r for r in list_resp.json() if r["hostname"] == "COMP-PC-01" and r["status"] in ("HELD", "ACTIVE")]
    assert len(res_list) > 0
    res_id = res_list[0]["id"]

    rel_resp = client.post(
        f"/api/admin/reservations/{res_id}/release",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert rel_resp.status_code == 200
    assert rel_resp.json()["status"] == "success"

    # PC must now be AVAILABLE for walk-in
    lock_resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert lock_resp.status_code == 200
    assert lock_resp.json()["state"] == "AVAILABLE"

def test_7_edge_cases_and_conflict_handling(client):
    """Test edge cases: unknown student, double-booking prevention, preemption."""
    admin_token = get_admin_token(client)

    # 1. Unknown student returns 404
    resp_unknown = client.post("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"}, json={
        "student_identifier": "NONEXISTENT_STUDENT_999",
        "hostname": "COMP-PC-01",
        "duration_minutes": 30
    })
    assert resp_unknown.status_code == 404

    # 2. Reserve PC-01 for STU002
    resp_res1 = client.post("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"}, json={
        "student_identifier": "STU002",
        "hostname": "COMP-PC-01",
        "duration_minutes": 60
    })
    assert resp_res1.status_code == 200

    # 3. Double-booking STU002 on another PC during same window must fail with 409 Conflict
    resp_double = client.post("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"}, json={
        "student_identifier": "STU002",
        "hostname": "COMP-PC-02",
        "duration_minutes": 60
    })
    assert resp_double.status_code == 409
    assert "already has an active reservation" in resp_double.json()["detail"]

    # 4. Overlapping booking on same PC COMP-PC-01 for another student must fail with 409 Conflict
    resp_overlap = client.post("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"}, json={
        "student_identifier": "STU001",
        "hostname": "COMP-PC-01",
        "duration_minutes": 60
    })
    assert resp_overlap.status_code == 409
    assert "already reserved" in resp_overlap.json()["detail"]

    # Clean up
    client.post("/api/admin/system/release-all", headers={"Authorization": f"Bearer {admin_token}"})


def test_8_multi_day_academic_reservation_and_extension(client):
    """Test real-world academic use cases: 5 days reservation, 30 days extension, purpose & reason tracking."""
    admin_token = get_admin_token(client)
    client.post("/api/admin/system/release-all", headers={"Authorization": f"Bearer {admin_token}"})

    # 1. Create a 5-day reservation for Final Year Capstone Project
    payload = {
        "student_identifier": "STU001",
        "hostname": "COMP-PC-01",
        "duration_days": 5,
        "purpose": "Final Year Capstone Project",
        "reason": "Autonomous Drone Navigation Simulation using ROS2",
        "force_preempt": True
    }
    resp = client.post("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"}, json=payload)
    assert resp.status_code == 200, f"5-day reservation creation failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "success"
    assert data["hostname"] == "COMP-PC-01"
    assert data["roll_no"] == "STU001"
    assert data["purpose"] == "Final Year Capstone Project"
    assert data["reason"] == "Autonomous Drone Navigation Simulation using ROS2"
    assert "remaining_display" in data
    assert "days remaining" in data["remaining_display"] or "4d" in data["remaining_display"]
    assert "time_window" in data
    res_id = data["reservation_id"]

    # 2. Check PC lock-state exposes academic purpose, project reason, and human-friendly time
    lock_resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert lock_resp.status_code == 200
    lock_data = lock_resp.json()
    assert lock_data["state"] == "HELD"
    assert lock_data["is_admin_dedicated"] is True
    assert lock_data["reserved_roll_no"] == "STU001"
    assert lock_data["purpose"] == "Final Year Capstone Project"
    assert lock_data["academic_reason"] == "Autonomous Drone Navigation Simulation using ROS2"
    assert lock_data["remaining_time_display"] is not None
    assert "days remaining" in lock_data["remaining_time_display"] or "4d" in lock_data["remaining_time_display"]
    assert lock_data["time_window"] is not None

    # 3. Extend by 30 days (1 month) for capstone defense revisions
    ext_resp = client.post(
        f"/api/admin/reservations/{res_id}/extend",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "additional_days": 30,
            "reason": "Reviewer requested hardware-in-the-loop stress testing and benchmark revisions"
        }
    )
    assert ext_resp.status_code == 200, f"30-day extension failed: {ext_resp.text}"
    ext_data = ext_resp.json()
    assert ext_data["status"] == "success"
    assert ext_data["extension_reason"] == "Reviewer requested hardware-in-the-loop stress testing and benchmark revisions"
    assert "remaining_display" in ext_data
    # 35 days remaining -> "1 mo 5d remaining" or "35 days remaining"
    assert ("mo" in ext_data["remaining_display"] or "month" in ext_data["remaining_display"] or "days remaining" in ext_data["remaining_display"])

    # 4. List dedicated reservations and verify structured metadata and notes trail
    list_resp = client.get("/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"})
    assert list_resp.status_code == 200
    res_list = [r for r in list_resp.json() if r["id"] == res_id]
    assert len(res_list) == 1
    record = res_list[0]
    assert record["purpose"] == "Final Year Capstone Project"
    assert "Autonomous Drone Navigation" in record["reason"]
    assert "Extended:" in record["notes"]
    assert "Reviewer requested hardware-in-the-loop" in record["notes"]

    # 5. Clean up
    client.post(f"/api/admin/reservations/{res_id}/release", headers={"Authorization": f"Bearer {admin_token}"})
    client.post("/api/admin/system/release-all", headers={"Authorization": f"Bearer {admin_token}"})

