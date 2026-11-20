import pytest
import requests
from playwright.sync_api import Page, expect

BASE_URL = "http://127.0.0.1:8000"

@pytest.fixture(autouse=True)
def reset_fleet_before_test():
    """Reset all workstations to AVAILABLE before and after tests."""
    try:
        login_res = requests.post(f"{BASE_URL}/api/auth/login", json={"roll_no": "admin", "password": "admin123"})
        if login_res.status_code == 200:
            token = login_res.json()["access_token"]
            requests.post(f"{BASE_URL}/api/admin/system/release-all", headers={"Authorization": f"Bearer {token}"})
    except Exception:
        pass
    yield
    try:
        login_res = requests.post(f"{BASE_URL}/api/auth/login", json={"roll_no": "admin", "password": "admin123"})
        if login_res.status_code == 200:
            token = login_res.json()["access_token"]
            requests.post(f"{BASE_URL}/api/admin/system/release-all", headers={"Authorization": f"Bearer {token}"})
    except Exception:
        pass

def test_kiosk_available_and_login_flow(page: Page):
    """Smoke test: Kiosk loads in AVAILABLE state and accepts student login."""
    page.goto(f"{BASE_URL}/workstation/COMP-PC-01")
    page.wait_for_selector("#loginView", state="visible", timeout=10000)
    
    expect(page.locator("#hostBadge")).to_contain_text("COMP-PC-01")
    expect(page.locator("#stateBadge")).to_be_visible()

    # Fill student login form
    page.fill("#loginRollInput", "STU001")
    page.fill("#loginPwInput", "stu123")
    page.click("#loginSubmitBtn")

    # Expect occupied view or message
    page.wait_for_selector("#occupiedView, .msg-success", state="visible", timeout=10000)

def test_portal_home_and_booking_tab(page: Page):
    """Smoke test: Web portal loads, navigation functions, and booking form renders."""
    page.goto(f"{BASE_URL}/")
    expect(page.locator(".brand-title")).to_contain_text("LABTRACK")
    
    # Check stats strip
    expect(page.locator(".stat-card").first).to_be_visible(timeout=10000)
    
    # Click Book Workstation tab
    booking_tab = page.locator("button.tab-btn:has-text('Book Workstation')")
    expect(booking_tab).to_be_visible()
    booking_tab.click()
    
    # Verify booking tab or auth requirement notice
    expect(page.locator("h2.card-title").first).to_be_visible()

def test_admin_portal_login_and_reserve_modal(page: Page):
    """Smoke test: Admin logs in, views Admin Operations, and opens Reserve PC modal."""
    page.goto(f"{BASE_URL}/")
    
    page.click("button:has-text('Sign In')")
    page.wait_for_selector(".modal-card", state="visible")
    
    page.fill(".modal-card input[type='text']", "admin")
    page.fill(".modal-card input[type='password']", "admin123")
    page.click(".modal-card button[type='submit']")
    
    admin_tab = page.locator("button.tab-btn:has-text('Admin Operations')")
    expect(admin_tab).to_be_visible(timeout=10000)
    
    reserve_btn = page.locator("button:has-text('+ Reserve PC for Student')").first
    expect(reserve_btn).to_be_visible()
    reserve_btn.click()
    
    expect(page.locator(".modal-card .card-title:has-text('Reserve Workstation for Student')")).to_be_visible()
    page.click(".modal-card .close-btn")

def test_faculty_portal_extra_labs(page: Page):
    """Smoke test: Faculty signs in and accesses Faculty Extra Labs."""
    page.goto(f"{BASE_URL}/")
    page.click("button:has-text('Sign In')")
    page.wait_for_selector(".modal-card", state="visible")
    page.fill(".modal-card input[type='text']", "faculty01")
    page.fill(".modal-card input[type='password']", "faculty123")
    page.click(".modal-card button[type='submit']")
    
    expect(page.locator("button.tab-btn:has-text('Faculty Extra Labs')")).to_be_visible(timeout=10000)
    expect(page.locator("button.tab-btn:has-text('Scheduled Lab Sessions')")).to_be_visible()

def test_club_lead_portal(page: Page):
    """Smoke test: Admin or club lead accesses Technical Clubs tab."""
    # Ensure STU002 is club_lead
    try:
        login_res = requests.post(f"{BASE_URL}/api/auth/login", json={"roll_no": "admin", "password": "admin123"})
        if login_res.status_code == 200:
            token = login_res.json()["access_token"]
            requests.post(f"{BASE_URL}/api/admin/users/4/role", headers={"Authorization": f"Bearer {token}"}, json={"role": "club_lead"})
    except Exception:
        pass

    page.goto(f"{BASE_URL}/")
    page.click("button:has-text('Sign In')")
    page.wait_for_selector(".modal-card", state="visible")
    page.fill(".modal-card input[type='text']", "STU002")
    page.fill(".modal-card input[type='password']", "stu123")
    page.click(".modal-card button[type='submit']")
    
    expect(page.locator("button.tab-btn:has-text('Technical Clubs')")).to_be_visible(timeout=10000)
