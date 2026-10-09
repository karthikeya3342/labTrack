import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from backend.app.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client

def get_token(client, roll_no, password):
    resp = client.post("/api/auth/login", json={"roll_no": roll_no, "password": password})
    assert resp.status_code == 200, f"Login failed for {roll_no}: {resp.text}"
    return resp.json()["access_token"]

@pytest.fixture(autouse=True)
def clean_database(client):
    admin_token = get_token(client, "admin", "admin123")
    client.post("/api/admin/system/release-all", headers={"Authorization": f"Bearer {admin_token}"})
    yield
    client.post("/api/admin/system/release-all", headers={"Authorization": f"Bearer {admin_token}"})

def test_future_club_event_does_not_immediately_lock_kiosk(client):
    """
    User Issue: Scheduled for 7:40 PM at 7:10 PM, but kiosk immediately showed club page.
    Fix: Workstation must remain AVAILABLE until 10 minutes before the event.
    """
    admin_token = get_token(client, "admin", "admin123")
    user_token = get_token(client, "STU001", "stu123")

    now = datetime.now(timezone.utc)
    # Event starting 45 minutes in the future
    event_start = now + timedelta(minutes=45)
    event_end = event_start + timedelta(hours=2)

    # 1. Propose Club Event for Computing Lab (Lab 1)
    prop_resp = client.post(
        "/api/clubs/events/request",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "club_id": 1,
            "title": "Future WebDev Workshop",
            "expected_attendees": 20,
            "lab_id": 1,
            "start_time": event_start.isoformat(),
            "end_time": event_end.isoformat(),
            "description": "Workshop starting in 45 minutes"
        }
    )
    assert prop_resp.status_code == 200, prop_resp.text
    event_id = prop_resp.json()["event_id"]

    # 2. Admin approves the future event
    appr_resp = client.post(
        f"/api/admin/club-events/{event_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"admin_notes": "Approved for 45 minutes later"}
    )
    assert appr_resp.status_code == 200, appr_resp.text

    # 3. VERIFY: Workstation COMP-PC-01 MUST REMAIN AVAILABLE right now!
    lock_resp = client.get("/api/pcs/COMP-PC-01/lock-state")
    assert lock_resp.status_code == 200
    lock_data = lock_resp.json()
    assert lock_data["state"] == "AVAILABLE", f"Expected AVAILABLE, got {lock_data['state']}"
    assert lock_data["is_club_event"] is False, "Future event must not show club screen 45 minutes early"

    # 4. Student can do walk-in check-in while it's available
    checkin_resp = client.post(
        "/api/agent/checkin",
        json={
            "hostname": "COMP-PC-01",
            "roll_no": "STU001",
            "password": "stu123"
        }
    )
    assert checkin_resp.status_code == 200, checkin_resp.text
    session_id = checkin_resp.json()["session_id"]

    # Close student walk-in session
    close_resp = client.post(
        "/api/agent/session-close",
        json={"session_id": session_id, "reason": "Walk-in complete"}
    )
    assert close_resp.status_code == 200

def test_faculty_extra_lab_reservation_and_student_login(client):
    """
    User Issue: Faculty extra lab reservation not working or students unable to login.
    Fix: Faculty reserves cohort; kiosk displays Faculty Practical Lab; students can log in.
    """
    import time
    admin_token = get_token(client, "admin", "admin123")

    now = datetime.now(timezone.utc)
    start = now
    end = now + timedelta(hours=2)
    batch = f"Cohort-{int(time.time())}"

    # 1. Admin/Faculty books extra lab for cohort in Software Engineering Lab (Lab 2)
    res = client.post(
        "/api/faculty/reserve-extra-lab",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "course_name": "Operating Systems Lab",
            "batch_name": batch,
            "student_count": 2,
            "preferred_lab_id": 2,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "notes": f"Faculty Extra Lab: Operating Systems Lab ({batch})"
        }
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "success"
    assert data["total_students_seated"] == 2

    # 2. Verify Kiosk lock-state on SE-PC-01 (Lab 2)
    lock_resp = client.get("/api/pcs/SE-PC-01/lock-state")
    assert lock_resp.status_code == 200
    lock_data = lock_resp.json()
    assert lock_data["state"] == "HELD"
    assert lock_data["is_faculty_lab"] is True
    assert "Operating Systems" in lock_data["course_name"]
    assert batch in lock_data["batch_name"]
    assert lock_data["faculty_name"] is not None

    # 3. Student STU002 logs in to SE-PC-01
    checkin_resp = client.post(
        "/api/agent/checkin",
        json={
            "hostname": "SE-PC-01",
            "roll_no": "STU002",
            "password": "stu123"
        }
    )
    assert checkin_resp.status_code == 200, checkin_resp.text
    sess_id = checkin_resp.json()["session_id"]
    assert sess_id is not None

    # Workstation is OCCUPIED
    lock_occ = client.get("/api/pcs/SE-PC-01/lock-state").json()
    assert lock_occ["state"] == "OCCUPIED"
    assert lock_occ["active_session"]["roll_no"] == "STU002"

    # Close session
    client.post("/api/agent/session-close", json={"session_id": sess_id, "reason": "Lab complete"})

def test_my_reservations_shows_clean_purpose_and_no_cohort_spam(client):
    """
    User Issue: My Reservations showed score/priority jargon and 20 individual cohort machines.
    Fix: My Reservations only shows user's personal booking with clean human purpose.
    """
    stu_token = get_token(client, "STU001", "stu123")
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=60, hours=2)
    end = start + timedelta(hours=2)

    # 1. Student books workstation with specific human purpose
    book_resp = client.post(
        "/api/reservations/advance",
        headers={"Authorization": f"Bearer {stu_token}"},
        json={
            "lab_id": 1,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "task_type": "Practice",
            "notes": "Computer Networks Socket Programming Assignment"
        }
    )
    assert book_resp.status_code == 200, book_resp.text
    res_id = book_resp.json()["reservation"]["id"]

    # 2. Query /api/reservations/my
    my_resp = client.get("/api/reservations/my", headers={"Authorization": f"Bearer {stu_token}"})
    assert my_resp.status_code == 200
    my_list = my_resp.json()
    assert len(my_list) >= 1
    my_item = next(r for r in my_list if r["id"] == res_id)
    assert my_item["purpose"] == "Computer Networks Socket Programming Assignment"
    # Ensure no cohort batch entries
    assert my_item.get("batch_name") is None

    # 3. Clean up
    del_resp = client.delete(f"/api/reservations/{res_id}", headers={"Authorization": f"Bearer {stu_token}"})
    assert del_resp.status_code == 200

def test_unauthenticated_cancellation_is_rejected(client):
    """
    User Issue: "without even logging i am able to cancel reservations"
    Fix: Strictly reject unauthenticated cancellation requests with 401 Unauthorized,
    and prevent unauthorized users from cancelling others' reservations with 403 Forbidden.
    """
    stu_token = get_token(client, "STU001", "stu123")
    other_token = get_token(client, "STU002", "stu123")
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=70, hours=1)
    end = start + timedelta(hours=2)

    # 1. Student STU001 books a workstation
    res = client.post(
        "/api/reservations/advance",
        headers={"Authorization": f"Bearer {stu_token}"},
        json={
            "lab_id": 1,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "task_type": "Practice",
            "notes": "Testing cancellation authentication"
        }
    )
    assert res.status_code == 200, res.text
    res_id = res.json()["reservation"]["id"]

    # 2. Attempt to cancel WITHOUT any token
    unauth_resp = client.delete(f"/api/reservations/{res_id}")
    assert unauth_resp.status_code == 401, f"Expected 401 Unauthorized, got {unauth_resp.status_code}"

    # 3. Attempt to cancel using a DIFFERENT student's token (STU002)
    forbidden_resp = client.delete(f"/api/reservations/{res_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert forbidden_resp.status_code == 403, f"Expected 403 Forbidden, got {forbidden_resp.status_code}"

    # 4. Valid cancellation with reserver's own token (STU001)
    valid_resp = client.delete(f"/api/reservations/{res_id}", headers={"Authorization": f"Bearer {stu_token}"})
    assert valid_resp.status_code == 200

def test_faculty_cohort_sequential_vs_balanced_allocation(client):
    """
    User Request:
    "we 3rd cse contain 107 student but one lab can't handle . so that two lab's assigned .
    one lab full and other lab remaining capacity or same lab's equal sharing , and remaining lab can be used the other students"
    """
    import time
    admin_token = get_token(client, "admin", "admin123")

    now = datetime.now(timezone.utc)
    start = now + timedelta(days=80)
    end = start + timedelta(hours=2)

    # Strategy 1: Sequential fill (30 students across Lab 1 [20 capacity] and Lab 2 [15 capacity])
    batch_seq = f"SeqCohort-{int(time.time())}"
    res_seq = client.post(
        "/api/faculty/reserve-extra-lab",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "course_name": "Distributed Systems",
            "batch_name": batch_seq,
            "student_count": 30,
            "allocation_strategy": "SEQUENTIAL",
            "preferred_lab_id": 1,
            "start_time": start.isoformat(),
            "end_time": end.isoformat()
        }
    )
    assert res_seq.status_code == 200, res_seq.text
    plan_seq = res_seq.json()["lab_partition_plan"]
    # Computing Lab (Lab 1) should be 100% full (20 allocated, 0 spare)
    lab1_seq = next(p for p in plan_seq if p["lab_id"] == 1)
    assert lab1_seq["allocated_students"] == 20
    assert lab1_seq["spare_pcs_available_for_others"] == 0
    # Software Eng Lab (Lab 2) gets remainder (10 allocated, 5 spare available for others!)
    lab2_seq = next(p for p in plan_seq if p["lab_id"] == 2)
    assert lab2_seq["allocated_students"] == 10
    assert lab2_seq["spare_pcs_available_for_others"] == 5

    # Strategy 2: Equal Balanced Sharing (30 students split equally across Lab 1 and Lab 2)
    start_bal = now + timedelta(days=81)
    end_bal = start_bal + timedelta(hours=2)
    batch_bal = f"BalCohort-{int(time.time())}"
    res_bal = client.post(
        "/api/faculty/reserve-extra-lab",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "course_name": "Cloud Computing",
            "batch_name": batch_bal,
            "student_count": 30,
            "allocation_strategy": "BALANCED",
            "preferred_lab_id": 1,
            "start_time": start_bal.isoformat(),
            "end_time": end_bal.isoformat()
        }
    )
    assert res_bal.status_code == 200, res_bal.text
    plan_bal = res_bal.json()["lab_partition_plan"]
    # Lab 1 gets 15, Lab 2 gets 15 (equal sharing!)
    lab1_bal = next(p for p in plan_bal if p["lab_id"] == 1)
    lab2_bal = next(p for p in plan_bal if p["lab_id"] == 2)
    assert lab1_bal["allocated_students"] == 15
    assert lab1_bal["spare_pcs_available_for_others"] == 5
    assert lab2_bal["allocated_students"] == 15
    assert lab2_bal["spare_pcs_available_for_others"] == 0

    # Test ending session early
    end_resp = client.post(
        "/api/faculty/sessions/end",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"batch_name": batch_seq}
    )
    assert end_resp.status_code == 200
    assert end_resp.json()["workstations_freed"] == 30

def test_club_end_event_and_admin_master_reset(client):
    """
    User Request:
    "and delete all club events , and also add to end the event so all the systems will be free i.e.. come back normal kisok ."
    """
    import time
    admin_token = get_token(client, "admin", "admin123")
    now = datetime.now(timezone.utc)
    start = now
    end = now + timedelta(hours=2)

    # 1. Create and approve a club event right now
    prop = client.post(
        "/api/clubs/events/request",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "club_id": 1,
            "title": f"GDG Flutter Devfest-{int(time.time())}",
            "expected_attendees": 10,
            "lab_id": 1,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "description": "Flutter Workshop"
        }
    )
    assert prop.status_code == 200
    ev_id = prop.json()["event_id"]

    appr = client.post(
        f"/api/admin/club-events/{ev_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"admin_notes": "Approved"}
    )
    assert appr.status_code == 200

    # System COMP-PC-01 should be HELD
    lock = client.get("/api/pcs/COMP-PC-01/lock-state").json()
    assert lock["state"] == "HELD"

    # 2. Conclude the club event via POST /api/clubs/events/{id}/end
    end_ev = client.post(
        f"/api/clubs/events/{ev_id}/end",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert end_ev.status_code == 200, end_ev.text

    # System COMP-PC-01 must immediately be AVAILABLE for walk-in
    lock_after = client.get("/api/pcs/COMP-PC-01/lock-state").json()
    assert lock_after["state"] == "AVAILABLE"

    # 3. Test Admin Master Reset: POST /api/admin/system/release-all
    reset_resp = client.post(
        "/api/admin/system/release-all",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "success"

    # Verify all PCs are AVAILABLE
    pcs_resp = client.get("/api/pcs")
    assert pcs_resp.status_code == 200
    all_pcs = pcs_resp.json()
    assert all(p["state"] == "AVAILABLE" for p in all_pcs if p["state"] != "MAINTENANCE")

def test_workstation_held_time_in_ist_and_iso(client):
    """
    User Issue: Live workstations showed UTC time (04:43 PM - 04:44 PM) instead of
    user's local Indian Standard Time (10:13 PM - 10:14 PM).
    Fix: Backend converts held_info.time_window to IST and exposes ISO start_time/end_time.
    """
    admin_token = get_token(client, "admin", "admin123")
    now = datetime.now(timezone.utc)
    # Event starting now and ending in 30 minutes
    start = now
    end = now + timedelta(minutes=30)

    # 1. Propose and auto-approve event
    ev_resp = client.post(
        "/api/clubs/events",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "club_id": 2, # BitSquad
            "title": "Intro to coding",
            "preferred_lab_id": 1,
            "expected_attendees": 20,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "auto_approve": True
        }
    )
    assert ev_resp.status_code == 200
    ev_id = ev_resp.json()["event_id"]

    try:
        # 2. Check /api/pcs
        pcs_resp = client.get("/api/pcs")
        assert pcs_resp.status_code == 200
        pcs = pcs_resp.json()
        comp_pc = next(p for p in pcs if p["hostname"] == "COMP-PC-01")
        assert comp_pc["state"] == "HELD"
        assert comp_pc["held_info"] is not None
        held = comp_pc["held_info"]
        assert held["hold_type"] == "club"
        assert "BitSquad" in held["who"]
        assert "start_time" in held
        assert "end_time" in held
        assert held["start_time"] is not None
        assert held["end_time"] is not None

        # Verify time_window matches IST (+05:30)
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        st_ist = start.astimezone(ist_tz)
        et_ist = end.astimezone(ist_tz)
        expected_window = f"{st_ist.strftime('%I:%M %p')} - {et_ist.strftime('%I:%M %p')}"
        assert held["time_window"] == expected_window
    finally:
        # Clean up
        client.post(
            f"/api/clubs/events/{ev_id}/end",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
