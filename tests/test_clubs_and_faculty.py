import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from backend.app.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture(scope="module", autouse=True)
def cleanup_after_module(client):
    yield
    admin_token = get_admin_token(client)
    # Restore STU001 and STU002 to student role
    client.post("/api/admin/users/3/role", headers={"Authorization": f"Bearer {admin_token}"}, json={"role": "student"})
    client.post("/api/admin/users/4/role", headers={"Authorization": f"Bearer {admin_token}"}, json={"role": "student"})
    # Close any active or held sessions on test machines
    client.post("/api/agent/close", json={"hostname": "COMP-PC-01", "reason": "Teardown cleanup"})
    client.post("/api/agent/close", json={"hostname": "AI-PC-01", "reason": "Teardown cleanup"})

def get_auth_token(client, roll_no="STU001", password="stu123"):
    resp = client.post("/api/auth/login", json={"roll_no": roll_no, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]

def get_admin_token(client):
    return get_auth_token(client, "admin", "admin123")

def test_1_get_technical_clubs(client):
    """Verify 5 official technical coding clubs are available with standardized assets."""
    resp = client.get("/api/clubs")
    assert resp.status_code == 200
    clubs = resp.json()
    assert len(clubs) >= 5
    slugs = [c["slug"] for c in clubs]
    assert "gdg" in slugs
    assert "bitsquad" in slugs
    assert "dataworks" in slugs
    assert "electronix" in slugs
    assert "robotics" in slugs

    # Verify logo urls are accessible
    gdg = next(c for c in clubs if c["slug"] == "gdg")
    assert "/static/clubs/gdg." in gdg["logo_url"]

def test_2_admin_promote_roles(client):
    """Admin promotes STU001 (id 3) to faculty and STU002 (id 4) to club_lead."""
    admin_token = get_admin_token(client)
    
    # Promote STU001 (Alice, id 3) to faculty
    resp = client.post(
        "/api/admin/users/3/role",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "faculty"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_role"] == "faculty"

    # Promote STU002 (Bob, id 4) to club_lead
    resp = client.post(
        "/api/admin/users/4/role",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "club_lead"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_role"] == "club_lead"

def test_3_faculty_extra_lab_reservation_and_m1_constraint(client):
    """
    Tests Faculty on-demand reservation:
    - Reserves workstations for 25 students across labs.
    - Leaves spare PCs in partially filled labs available for walk-ins.
    - Strictly enforces Indian College Rule M1: rejects duplicate lab booking for same batch on same day.
    """
    # STU001 is now faculty, generate fresh token
    faculty_token = get_auth_token(client, "STU001")
    
    # Unique batch name per test execution
    batch_name = f"3rd Year CSE - Section A {int(datetime.now().timestamp())}"

    # Dynamic future day to prevent M2 self-clash across repeated test runs
    days_ahead = 10 + (int(datetime.now().timestamp()) % 500)
    start_time = datetime.now(timezone.utc) + timedelta(days=days_ahead, hours=2)
    end_time = start_time + timedelta(hours=2)

    req_payload = {
        "course_name": "Operating Systems Lab",
        "batch_name": batch_name,
        "student_count": 25,
        "preferred_lab_id": 1,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "notes": "Extra Makeup Lab for OS concurrency practicals"
    }

    resp = client.post(
        "/api/faculty/reserve-extra-lab",
        headers={"Authorization": f"Bearer {faculty_token}"},
        json=req_payload
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["total_students_seated"] == 25
    assert len(data["lab_partition_plan"]) >= 2
    # Check that spare PCs were left available in partially filled lab
    second_lab = data["lab_partition_plan"][1]
    assert second_lab["spare_pcs_available_for_others"] > 0

    # Constraint M1 Violation Test:
    # Attempting to schedule another practical lab for the SAME batch on the SAME calendar day
    conflict_start = start_time + timedelta(hours=3)
    conflict_end = conflict_start + timedelta(hours=2)

    conflict_payload = {
        "course_name": "Database Systems Lab",
        "batch_name": batch_name, # SAME BATCH
        "student_count": 10,
        "preferred_lab_id": 1,
        "start_time": conflict_start.isoformat(),
        "end_time": conflict_end.isoformat(),
        "notes": "DBMS Extra Lab"
    }

    conflict_resp = client.post(
        "/api/faculty/reserve-extra-lab",
        headers={"Authorization": f"Bearer {faculty_token}"},
        json=conflict_payload
    )
    assert conflict_resp.status_code == 409
    detail = conflict_resp.json()["detail"]
    assert "Constraint M1 Violation" in detail
    assert "at most 1 practical lab per day" in detail

def test_4_technical_club_event_lifecycle_and_live_roster(client):
    """
    Tests complete Technical Coding Club workflow:
    1. Club Lead requests lab for event 'Intro to Development'.
    2. Admin approves event; all PCs in lab transition to HELD.
    3. Workstation lock-state returns is_club_event=True, club name, logo, event title.
    4. Any registered student logs in without individual pre-assignment restriction.
    5. Session is tagged with club_event_id; live attendance roster reflects participant.
    """
    # STU002 is club_lead, generate fresh token
    lead_token = get_auth_token(client, "STU002")
    admin_token = get_admin_token(client)

    now = datetime.now(timezone.utc)
    # Event active now to test immediate lock state and login
    start_time = now - timedelta(minutes=5)
    end_time = now + timedelta(hours=2)

    # 1. Request Event for GDG (Club ID 1) in Lab 3
    req_resp = client.post(
        "/api/clubs/events/request",
        headers={"Authorization": f"Bearer {lead_token}"},
        json={
            "club_id": 1,
            "title": f"Intro to Development {int(now.timestamp())}",
            "description": "Hands-on Web & Cloud development workshop by GDG",
            "lab_id": 3,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat()
        }
    )
    assert req_resp.status_code == 200, req_resp.text
    event_id = req_resp.json()["event_id"]

    # 2. Admin Approves Event
    appr_resp = client.post(
        f"/api/admin/clubs/events/{event_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"admin_notes": "Approved for GDG. Workstations allocated."}
    )
    assert appr_resp.status_code == 200, appr_resp.text
    assert appr_resp.json()["status"] == "approved"

    # 3. Workstation Lock-State Verification on AI-PC-01 (in Lab 3)
    lock_resp = client.get("/api/pcs/AI-PC-01/lock-state")
    assert lock_resp.status_code == 200
    lock_data = lock_resp.json()
    assert lock_data["state"] == "HELD"
    assert lock_data["is_club_event"] is True
    assert "Google Developer Groups" in lock_data["club_name"]
    assert "Intro to Development" in lock_data["event_title"]
    assert "/static/clubs/gdg." in lock_data["club_logo_url"]

    # 4. Open Attendee Check-In: Student STU003 logs in
    checkin_resp = client.post(
        "/api/agent/checkin",
        json={
            "hostname": "AI-PC-01",
            "roll_no": "STU003",
            "password": "stu123"
        }
    )
    assert checkin_resp.status_code == 200, checkin_resp.text
    session_id = checkin_resp.json()["session_id"]
    assert session_id is not None

    # Workstation state is now OCCUPIED
    lock_after = client.get("/api/pcs/AI-PC-01/lock-state").json()
    assert lock_after["state"] == "OCCUPIED"
    assert lock_after["active_session"]["roll_no"] == "STU003"

    # 5. Live Attendance Roster Verification
    roster_resp = client.get(f"/api/clubs/events/{event_id}/roster")
    assert roster_resp.status_code == 200
    roster_data = roster_resp.json()
    assert roster_data["metrics"]["total_attendees"] >= 1
    assert roster_data["metrics"]["active_now"] >= 1
    attendees = roster_data["roster"]
    stu3_entry = next(a for a in attendees if a["roll_no"] == "STU003")
    assert stu3_entry["hostname"] == "AI-PC-01"
    assert stu3_entry["session_status"] == "ACTIVE"

    # Cleanup: close session
    close_resp = client.post(
        "/api/agent/session-close",
        json={"session_id": session_id, "reason": "Test Complete"}
    )
    assert close_resp.status_code == 200

def test_5_taskpool_waitlist_and_dynamic_aging_auto_promotion(client):
    """
    Tests Dynamic TaskPool Waitlist & Auto-Promotion:
    1. Student joins waitlist.
    2. Dynamic aging increases priority score over waiting time.
    3. Closing a session auto-promotes the queued student to HELD state.
    """
    admin_token = get_admin_token(client)
    # Clear any prior queued entries for STU004
    existing_wl = client.get("/api/scheduler/waitlist").json()
    for e in existing_wl:
        if e["roll_no"] == "STU004":
            client.delete(f"/api/scheduler/waitlist/{e['id']}", headers={"Authorization": f"Bearer {admin_token}"})

    token = get_auth_token(client, "STU004")

    # 1. Join Waitlist
    join_resp = client.post(
        "/api/scheduler/waitlist/join",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "task_type": "Senior Project",
            "target_lab_id": 1,
            "software_required": ["Python", "VSCode"]
        }
    )
    assert join_resp.status_code == 200, join_resp.text
    entry_id = join_resp.json()["entry_id"]
    assert join_resp.json()["base_priority"] == 80

    # 2. Query Waitlist & Dynamic Aging
    waitlist_resp = client.get("/api/scheduler/waitlist")
    assert waitlist_resp.status_code == 200
    entries = waitlist_resp.json()
    assert any(e["id"] == entry_id for e in entries)

    # 3. Simulate session close on COMP-PC-01 in Lab 1 to trigger auto-promotion
    # Ensure COMP-PC-01 session is closed if any exists
    client.post("/api/agent/close", json={"hostname": "COMP-PC-01", "reason": "Pre-test reset"})

    # Now STU005 logs into COMP-PC-01
    checkin_resp = client.post("/api/agent/checkin", json={"hostname": "COMP-PC-01", "roll_no": "STU005", "password": "stu123"})
    assert checkin_resp.status_code == 200, checkin_resp.text
    s_id = checkin_resp.json()["session_id"]

    sess_pc = client.get("/api/pcs/COMP-PC-01/lock-state").json()
    assert sess_pc["state"] == "OCCUPIED"

    # Close session -> Triggers promote_next_taskpool_entry
    close_resp = client.post(
        f"/api/admin/sessions/{s_id}/force-release",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert close_resp.status_code == 200
    promoted = close_resp.json().get("promoted_waitlist_entry")
    assert promoted is not None
    assert promoted["entry_id"] == entry_id
    assert promoted["roll_no"] == "STU004"

    # COMP-PC-01 is now held for promoted student STU004
    held_state = client.get("/api/pcs/COMP-PC-01/lock-state").json()
    assert held_state["state"] == "HELD"
    assert held_state["reserved_roll_no"] == "STU004"
