import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from backend.app.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client

def get_auth_token(client, roll_no="STU001", password="stu123"):
    resp = client.post("/api/auth/login", json={"roll_no": roll_no, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]

def test_section6_task_based_allocation_practice_to_lab1(client):
    """Proposal Section 6: Practice sessions allocate to Computing Lab (Lab 1)."""
    token = get_auth_token(client, "STU001")
    start = datetime.now(timezone.utc) + timedelta(days=2, hours=1)
    end = start + timedelta(hours=2)

    resp = client.post(
        "/api/reservations/advance",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "task_type": "Practice",
            "software_required": [],
            "start_time": start.isoformat(),
            "end_time": end.isoformat()
        }
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["allocation"]["priority_score"] == 20  # Practice base weight
    assert data["reservation"]["lab_name"] == "Computing Lab"
    assert "Computing Lab" in data["allocation"]["allocation_basis"]

def test_section6_task_based_allocation_senior_project_to_lab2(client):
    """Proposal Section 6: Senior Project allocates to Software Eng Lab (Lab 2) with high priority."""
    token = get_auth_token(client, "STU002")
    start = datetime.now(timezone.utc) + timedelta(days=2, hours=3)
    end = start + timedelta(hours=2)
    deadline = start + timedelta(hours=12)

    resp = client.post(
        "/api/reservations/advance",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "task_type": "Senior Project",
            "software_required": [],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "deadline": deadline.isoformat()
        }
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["allocation"]["priority_score"] >= 80  # Senior Project priority >= 80
    assert data["reservation"]["lab_name"] == "Software Engineering Lab"

def test_section6_task_based_allocation_gpu_to_lab3(client):
    """Proposal Section 6: PyTorch GPU allocates to AI & High-Performance Lab (Lab 3)."""
    token = get_auth_token(client, "STU003")
    import time
    offset = 100 + (int(time.time() * 10) % 500)
    start = datetime.now(timezone.utc) + timedelta(days=offset, hours=5)
    end = start + timedelta(hours=2)

    resp = client.post(
        "/api/reservations/advance",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "task_type": "Coursework",
            "software_required": ["PyTorch GPU"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat()
        }
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert "AI & High Performance Lab" in data["reservation"]["lab_name"]
    assert "Lab 3" in data["allocation"]["allocation_basis"]

def test_section6_overflow_rule_computing_lab_to_se_lab(client):
    """Proposal Section 6 Overflow Rule: Small tasks use Software Eng Lab only when Computing Lab is full."""
    import subprocess

    token = get_auth_token(client, "STU004")
    start = datetime.now(timezone.utc) + timedelta(days=3, hours=10)
    end = start + timedelta(hours=2)

    # Book out all 20 PCs in Lab 1 for this time window via psql
    sql = f"""
        INSERT INTO reservations (student_id, pc_id, task_type, time_range, status)
        SELECT 1, id, 'Practice', tstzrange('{start.isoformat()}', '{end.isoformat()}', '[)'), 'PENDING'
        FROM pcs WHERE lab_id = 1
        ON CONFLICT DO NOTHING;
    """
    subprocess.run([
        "/home/karthikeya/labTrack/bin/psql",
        "-h", "/home/karthikeya/labTrack/.pg_socket",
        "-d", "labtrack",
        "-c", sql
    ], check=True)

    # Now request a Practice task for the exact same window
    resp = client.post(
        "/api/reservations/advance",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "task_type": "Practice",
            "software_required": [],
            "start_time": start.isoformat(),
            "end_time": end.isoformat()
        }
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    # Must have overflowed to Lab 2 (Software Engineering Lab)
    assert data["reservation"]["lab_name"] == "Software Engineering Lab"
    assert data["allocation"]["overflow_applied"] is True
    assert "Overflow Rule Applied" in data["allocation"]["allocation_basis"]
