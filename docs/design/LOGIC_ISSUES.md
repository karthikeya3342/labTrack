# LabTrack Logic Issues Log

**Status**: Active  
**Policy**: In accordance with the **Logic is Frozen** mandate, no backend code, database procedures, daemon scripts, or frontend state management/API payloads have been modified. The issues cataloged below represent UX and workflow shortcomings that strictly require backend or architectural logic changes to be fully resolved. Recommendations for future product releases are provided.

---

### LOGIC-01: Accidental Click Protection on Desktop Floating HUD "Logout & Relock"

- **Surface**: Kiosk Floating Telemetry HUD (`frontend/workstation_screen.html`)
- **Current Behavior**: Clicking `#floatingBarWidget .dock-btn-logout-cool` calls `handleLogout()`, which immediately fires `GET http://127.0.0.1:8008/lock` and terminates the student's cgroups sandbox session without a client-side confirmation or hold-to-confirm mechanism.
- **Problem**: Because the HUD pill floats over arbitrary desktop applications (VS Code, terminal, browser), an inadvertent mouse click can abruptly terminate hours of active coursework or research scripts.
- **Frontend Presentation Mitigation**: In the design overhaul, we provide a visual 2-step click confirmation dialog or a "Hold for 1.5s to Relock" presentation wrapper that intercepts the click before triggering the untouched `handleLogout()` handler.
- **Recommended Logic Fix**: The backend session daemon (`agent.py` / `daemon/`) should support a `/api/session/terminate-request` handshake with a 10-second graceful cancellation window, allowing a student to abort accidental session termination.

---

### LOGIC-02: Client-Server Clock Drift on Kiosk Grace Countdown

- **Surface**: Kiosk Held State Grace Timer (`#graceCountdown` in `frontend/workstation_screen.html`)
- **Current Behavior**: The grace period countdown (15 minutes) is decremented locally using `setInterval(tickCountdown, 1000)` based on the client machine's local clock and a remaining seconds integer parsed on initial load.
- **Problem**: If the physical workstation clock drifts from the central PostgreSQL database server time by even 60 seconds, the client kiosk countdown may display remaining grace time even after the backend cron has auto-cancelled the booking as `NO_SHOW`, leading to 403/409 errors when the student attempts to unlock.
- **Frontend Presentation Mitigation**: Polling lock-state every 5 seconds resyncs `remainingSeconds` from the API. Tabular numerals prevent visual jitter.
- **Recommended Logic Fix**: The `/api/pcs/{HOSTNAME}/lock-state` endpoint should return an absolute server epoch timestamp (`expires_at_utc`) and the server's current timestamp (`server_time_utc`), allowing monotonic drift calculation.

---

### LOGIC-03: Force Preempt Impact Transparency in API Payloads

- **Surface**: Admin Dedicated Allocation Modal (`frontend/index.html` - `TabAdmin`)
- **Current Behavior**: Checking "Force Preempt" sends `force_preempt: true` in `POST /api/admin/reservations/dedicated`. If another student is actively logged in, their session is abruptly closed via backend database trigger without returning a simulation of who will be displaced beforehand.
- **Problem**: The admin cannot preview *which* student session will be preempted prior to clicking the confirmation button.
- **Frontend Presentation Mitigation**: Add an interactive confirmation modal step when "Force Preempt" is checked, warning the admin of immediate session termination.
- **Recommended Logic Fix**: Provide a dry-run endpoint (`POST /api/admin/reservations/dedicated/simulate`) returning displaced session details (`displaced_roll_no`, `displaced_student_name`, `session_start_time`) so the UI can present an explicit displacement impact warning.

---

### LOGIC-04: Multi-Day Dedicated Allocation Expiry Notification

- **Surface**: Admin Operations & Workstation Kiosk
- **Current Behavior**: Dedicated reservations simply transition to expired at their end date/time. The student has no automated mechanism (SMS/email/in-app alert) warned 24 hours prior to expiration to save data or request an extension.
- **Frontend Presentation Mitigation**: Kiosk displays an amber urgency escalation badge when `< 48 hours` remain.
- **Recommended Logic Fix**: Implement an asynchronous backend task notifying the student when 24 hours remain on their dedicated allocation.
