import os
import time
import requests
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
BEFORE_DIR = os.path.abspath("before")
os.makedirs(os.path.join(BEFORE_DIR, "kiosk"), exist_ok=True)
os.makedirs(os.path.join(BEFORE_DIR, "portal"), exist_ok=True)

def reset_fleet(admin_token):
    requests.post(f"{BASE_URL}/api/admin/system/release-all", headers={"Authorization": f"Bearer {admin_token}"})

def get_token(roll_no, password):
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"roll_no": roll_no, "password": password})
    return res.json()["access_token"] if res.status_code == 200 else None

def capture_all():
    admin_token = get_token("admin", "admin123")
    reset_fleet(admin_token)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        
        # 1. KIOSK SCREENSHOTS (1920x1080 and 1366x768)
        kiosk_viewports = [
            ("1920x1080", 1920, 1080),
            ("1366x768", 1366, 768)
        ]

        # State 1: AVAILABLE
        reset_fleet(admin_token)
        for name, w, h in kiosk_viewports:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{BASE_URL}/workstation/COMP-PC-01")
            page.wait_for_selector("#loginView", state="visible")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(BEFORE_DIR, "kiosk", f"kiosk-available-{name}.png"))
            page.close()

        # State 2: OCCUPIED + Session Active
        reset_fleet(admin_token)
        # Login on COMP-PC-01 as STU001
        requests.post(f"{BASE_URL}/api/agent/checkin", json={
            "hostname": "COMP-PC-01", "roll_no": "STU001", "password": "stu123"
        })
        for name, w, h in kiosk_viewports:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{BASE_URL}/workstation/COMP-PC-01")
            page.wait_for_selector("#occupiedView", state="visible")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(BEFORE_DIR, "kiosk", f"kiosk-occupied-{name}.png"))
            page.close()

        # State 3: HUD Floating Dock (?floating=1)
        for name, w, h in kiosk_viewports:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{BASE_URL}/workstation/COMP-PC-01?floating=1")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(BEFORE_DIR, "kiosk", f"kiosk-hud-floating-{name}.png"))
            page.close()

        # State 4: HELD - Admin Dedicated Allocation
        reset_fleet(admin_token)
        requests.post(f"{BASE_URL}/api/admin/reservations/dedicated", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "student_identifier": "STU001",
            "hostname": "COMP-PC-01",
            "duration_days": 28,
            "purpose": "Final Year Capstone Project",
            "reason": "Autonomous Drone Navigation ROS2 Simulation",
            "force_preempt": True
        })
        for name, w, h in kiosk_viewports:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{BASE_URL}/workstation/COMP-PC-01")
            page.wait_for_selector("#individualHeldContext", state="visible")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(BEFORE_DIR, "kiosk", f"kiosk-held-dedicated-{name}.png"))
            page.close()

        # State 5: MAINTENANCE
        reset_fleet(admin_token)
        requests.post(f"{BASE_URL}/api/admin/pcs/COMP-PC-01/maintenance", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "is_maintenance": True, "reason": "RAM Diagnostics & Memory Bus Stress Testing"
        })
        for name, w, h in kiosk_viewports:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{BASE_URL}/workstation/COMP-PC-01")
            page.wait_for_selector("#maintenanceView", state="visible")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(BEFORE_DIR, "kiosk", f"kiosk-maintenance-{name}.png"))
            page.close()

        reset_fleet(admin_token)

        # 2. PORTAL SCREENSHOTS (375, 768, 1280, 1920)
        portal_viewports = [
            ("mobile-375", 375, 812),
            ("tablet-768", 768, 1024),
            ("laptop-1280", 1280, 800),
            ("desktop-1920", 1920, 1080)
        ]

        # Unauthenticated Grid
        for name, w, h in portal_viewports:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{BASE_URL}/")
            page.wait_for_selector(".stat-card")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(BEFORE_DIR, "portal", f"portal-grid-guest-{name}.png"), full_page=True)
            page.close()

        # Admin View (Operations, stats, fleet, dedicated reservations)
        for name, w, h in [("laptop-1280", 1280, 800), ("desktop-1920", 1920, 1080)]:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{BASE_URL}/")
            # Sign in as admin
            page.click("button:has-text('Sign In')")
            page.wait_for_selector(".modal-card", state="visible")
            page.fill(".modal-card input[type='text']", "admin")
            page.fill(".modal-card input[type='password']", "admin123")
            page.click(".modal-card button[type='submit']")
            page.wait_for_selector("button.tab-btn:has-text('Admin Operations')")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(BEFORE_DIR, "portal", f"portal-admin-dashboard-{name}.png"), full_page=True)
            
            # Open Reserve PC Modal
            page.click("button:has-text('+ Reserve PC for Student')")
            page.wait_for_selector(".modal-card h3:has-text('Reserve Workstation')")
            time.sleep(0.5)
            page.screenshot(path=os.path.join(BEFORE_DIR, "portal", f"portal-admin-reserve-modal-{name}.png"))
            page.close()

        # Faculty View (Extra Labs & Scheduled Sessions)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{BASE_URL}/")
        page.click("button:has-text('Sign In')")
        page.wait_for_selector(".modal-card", state="visible")
        page.fill(".modal-card input[type='text']", "faculty01")
        page.fill(".modal-card input[type='password']", "faculty123")
        page.click(".modal-card button[type='submit']")
        page.wait_for_selector("button.tab-btn:has-text('Faculty Extra Labs')")
        time.sleep(0.5)
        page.screenshot(path=os.path.join(BEFORE_DIR, "portal", "portal-faculty-extralabs-laptop.png"), full_page=True)
        
        page.click("button.tab-btn:has-text('Scheduled Lab Sessions')")
        time.sleep(0.5)
        page.screenshot(path=os.path.join(BEFORE_DIR, "portal", "portal-faculty-scheduled-laptop.png"), full_page=True)
        page.close()

        # Student View (Booking tab & My Reservations)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{BASE_URL}/")
        page.click("button:has-text('Sign In')")
        page.wait_for_selector(".modal-card", state="visible")
        page.fill(".modal-card input[type='text']", "STU001")
        page.fill(".modal-card input[type='password']", "stu123")
        page.click(".modal-card button[type='submit']")
        page.wait_for_selector("button.tab-btn:has-text('Book Workstation')")
        time.sleep(0.5)
        page.screenshot(path=os.path.join(BEFORE_DIR, "portal", "portal-student-booking-laptop.png"), full_page=True)
        page.click("button.tab-btn:has-text('My Reservations')")
        time.sleep(0.5)
        page.screenshot(path=os.path.join(BEFORE_DIR, "portal", "portal-student-reservations-laptop.png"), full_page=True)
        page.close()

        # Club Lead View
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{BASE_URL}/")
        page.click("button:has-text('Sign In')")
        page.wait_for_selector(".modal-card", state="visible")
        page.fill(".modal-card input[type='text']", "STU002")
        page.fill(".modal-card input[type='password']", "stu123")
        page.click(".modal-card button[type='submit']")
        page.wait_for_selector("button.tab-btn:has-text('Technical Clubs')")
        time.sleep(0.5)
        page.screenshot(path=os.path.join(BEFORE_DIR, "portal", "portal-clubs-lead-laptop.png"), full_page=True)
        page.close()

        browser.close()

    reset_fleet(admin_token)
    print("All baseline BEFORE screenshots captured successfully in before/")

if __name__ == "__main__":
    capture_all()
