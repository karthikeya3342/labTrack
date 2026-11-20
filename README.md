# LabTrack: University Computer Lab Resource Management & Intelligent Scheduling System

LabTrack is a complete, native Linux university computer laboratory resource management, scheduling, and workstation control plane built with **FastAPI**, **PostgreSQL 16**, **systemd**, and **cgroups v2**.

It implements the mathematical formulations and intelligent scheduling strategies from:
> **Chao He & Shi Cheng (2025)**: *Simulation Optimisation of Laboratory Resources in Universities with Intelligent Scheduling Strategies*.

---

## 1. System Architecture & Lab Topology

```
                  +-------------------------------------------------------------+
                  |         CAMPUS FIREWALL / CAPTIVE PORTAL GATEWAY           |
                  |                https://10.10.10.2:8090/httpclient.html      |
                  +------------------------------+------------------------------+
                                                 | (WAN Internet Access)
  ===============================================|==============================================
  LOCAL COMPUTER LAB SUBNET / ETHERNET SWITCH (DIRECT LAN - NEVER BLOCKED BY CAMPUS FIREWALL)
  ===============================================|==============================================
         |                                       |                                       |
         v                                       v                                       v
+-------------------------------+ +-------------------------------+ +-------------------------------+
|  MACHINE 1: LAB SERVER PC     | | MACHINE 2: CLIENT WORKSTATION | | MACHINE 3: CLIENT WORKSTATION |
|  - PostgreSQL 16 Relational   | |   (e.g., COMP-PC-01)          | |   (e.g., COMP-PC-02)          |
|  - FastAPI Backend (:8000)    | | - Workstation Screen Greeter  | | - Workstation Screen Greeter  |
|  - Web Portal & Admin Dash    | | - labtrack_agent.py (Daemon)  | | - labtrack_agent.py (Daemon)  |
|  - Research GA Scheduler      | | - cgroups v2 /proc Telemetry  | | - cgroups v2 /proc Telemetry  |
+-------------------------------+ +-------------------------------+ +-------------------------------+
```

### Configured Labs & Workstations (45 Systems)
1. **Lab 1: Computing Lab (`COMP-PC-01` to `COMP-PC-20`)**: 20 general computing workstations with Intel Core i7-13700, 32GB RAM.
2. **Lab 2: Software Engineering Lab (`SE-PC-01` to `SE-PC-15`)**: 15 development workstations with Intel Core i7-14700, NVIDIA T1000 GPUs, 32GB RAM.
3. **Lab 3: AI & High-Performance Lab (`AI-PC-01` to `AI-PC-10`)**: 10 high-performance compute nodes with AMD Ryzen 9 7950X, NVIDIA GeForce RTX 4090 24GB VRAM, 64GB RAM.

---

## 2. Key Features & Workflows

### A. Academic Multi-Day Workstation Allocation (Admin)
- **Dedicated Holds**: Admins can reserve a workstation for a specific student for multi-day periods (e.g., 5 days, 1 month, or custom durations) for academic research, final year capstone projects, or faculty-sponsored research.
- **Persistence Across Logouts**: Unlike standard walk-in sessions, dedicated allocations remain exclusively locked for the designated student even after session logout until the allocation expires.
- **Quick Extensions**: 1-click extension buttons (`+5 Days`, `+1 Week`, `+1 Month`) and custom extension modals with mandatory audit reasons.
- **Preemption Handling**: Admin override with conflict detection and automated audit logs.

### B. 20-Minute Grace Period & Pre-Arrival Hold Policy
- **20-Minute Grace Window**: Reserved students have a 20-minute grace window from the scheduled start time to check in at their assigned PC before the slot is auto-cancelled as `NO_SHOW` and opened to walk-ins.
- **10-Minute Pre-Arrival Hold Buffer**: Workstations transition into `HELD` state up to 10 minutes prior to scheduled start time, preventing walk-in students from occupying a machine right before a reservation begins.
- **Zero-Jitter Tabular Countdown**: Built with CSS layout containment (`contain: layout style;`) and monospace tabular numerals (`font-variant-numeric: tabular-nums`) to ensure timer countdowns never resize or reflow surrounding UI.

### C. Technical Clubs & Faculty Practical Labs
- **Technical Club Takeover**: Club leads propose workshops; upon admin approval, assigned workstations lock into custom-branded club check-in mode.
- **Faculty Practical Labs**: Faculty schedule cohort sessions with live capacity tracking and secondary overflow lab support.

### D. Offline Design System (WCAG 2.2 Level AA Compliant)
- **Zero External Network Dependencies**: 100% offline-vendored fonts (`Inter` and `JetBrains Mono`) and vector SVG icon suite (no CDN requests).
- **Kiosk State Engine**: 8 distinct, accessible fullscreen lock states (Available, Personal Hold, Dedicated Hold, Faculty Lab, Club Event, Maintenance, Access Denied, Active Session).
- **Interactive State Gallery**: Dev harness at `/static/dev_states.html` for inspecting every kiosk state and modal variant.
- **Session Telemetry HUD**: Floating dark telemetry dock displaying real-time CPU% and RAM% with a 2-step accidental-click protected "Logout & Relock" button.

---

## 3. Workstation Agent & Captive Portal Bridge

### Workstation Lock Screen (`frontend/workstation_screen.html`)
- Boots into fullscreen kiosk mode (`google-chrome --kiosk`).
- Polls `/api/pcs/<HOSTNAME>/lock-state` over the local lab subnet.
- **HELD State**: Displays reserved student name, roll number, purpose, and live countdown. Unauthorized logins are strictly blocked (`403 Forbidden`).
- **AVAILABLE State**: Permits walk-ins with automated schedule backfilling up to 2 hours.
- **OCCUPIED State**: Shows active session dashboard with live CPU/RAM metrics and logout controls.

### Captive Portal Auto-Authenticator Bridge
- Target URL: `https://10.10.10.2:8090/httpclient.html`
- When a student unlocks the workstation, the daemon submits a background authentication POST (`mode=191`), granting instant campus internet access without manual browser login.
- Upon session logout, the agent sends a release POST (`mode=193`) to prevent internet quota leakage.

### Linux Security & cgroups v2 Sandboxing
- Creates isolated temporary workspaces in `/tmp/labtrack/workspace_<session_id>` with secure post-logout wiping.
- Enforces cgroups v2 memory and CPU quotas (`/sys/fs/cgroup/labtrack/session_<id>`).
- Reaps zombie/orphan processes with `os.waitpid(-1, os.WNOHANG)`.
- Scans process tree for unauthorized processes (cryptominers: `xmrig`, `minerd`; torrent clients: `transmission`, `qbittorrent`; games: `steam`, `lutris`) and applies staged termination (`SIGTERM` $\to$ grace $\to$ `SIGKILL`).

---

## 4. Quick Start: Central Lab Server

### 1. Initialize PostgreSQL 16 Database
```bash
./scripts/setup_postgres.sh
```
Initializes the local PostgreSQL 16 cluster, creates the `labtrack` database, installs schema and GiST range exclusion constraints, compiles stored procedures (`procedures.sql`), and seeds all 45 workstations and test users.

### 2. Start the Server Control Plane
```bash
./scripts/start_server.sh
# Listens on 0.0.0.0:8000
```
- **Web Portal**: `http://<SERVER_IP>:8000/`
- **Workstation Kiosk**: `http://<SERVER_IP>:8000/workstation/COMP-PC-01`
- **Dev State Gallery**: `http://<SERVER_IP>:8000/static/dev_states.html`
- **OpenAPI Docs**: `http://<SERVER_IP>:8000/docs`

### 3. Stop the Server
```bash
# Stop FastAPI backend
pkill -f "uvicorn.*backend.app.main:app"

# Stop PostgreSQL instance (optional)
pkill -f "postgres.*labTrack"
```

---

## 5. Workstation Client Installation (Target PC)

The central server serves the client installer and daemon directly over HTTP. You can set up any physical lab PC on the same LAN subnet with a single turnkey command:

### 1. Automated Installation on Client PC (e.g. `COMP-PC-01`)
Open a terminal on the client workstation and run:
```bash
curl -sSL http://<SERVER_IP>:8000/install-agent.sh -o /tmp/install.sh && sudo bash /tmp/install.sh COMP-PC-01 http://<SERVER_IP>:8000
```
*(Or with `wget`:)*
```bash
wget -qO /tmp/install.sh http://<SERVER_IP>:8000/install-agent.sh && sudo bash /tmp/install.sh COMP-PC-01 http://<SERVER_IP>:8000
```

This automatically:
1. Verifies LAN network connectivity to the central server.
2. Installs required python dependencies (`psutil`, `requests`).
3. Downloads the workstation daemon to `/opt/labtrack/labtrack_agent.py`.
4. Creates and starts the `labtrack-agent.service` systemd service.
5. Configures fullscreen boot kiosk auto-start (`/etc/xdg/autostart/labtrack-kiosk.desktop`).
6. Installs the desktop relock shortcut and system-wide `labtrack-logout` CLI.

### 2. Client Service Management
```bash
# Check service status
sudo systemctl status labtrack-agent.service

# Stop service
sudo systemctl stop labtrack-agent.service

# Disable auto-start on boot
sudo systemctl disable labtrack-agent.service

# Close fullscreen kiosk browser
pkill -f "google-chrome.*kiosk" || pkill -f "chromium.*kiosk" || pkill -f "firefox.*kiosk"
```

---

## 6. Automated Verification & Testing

### Run Backend Unit & Integration Tests (34 Tests)
```bash
./venv/bin/pytest tests/test_*.py -v
```
Verifies:
- Individual and Admin Dedicated workstation reservations with preemption and extensions.
- Technical clubs event proposals, approval workflows, and emergency release.
- Faculty practical lab cohort scheduling and secondary overflow allocation.
- Inactivity / idle timeout tracking and auto-release.
- Core MVP workflows: walk-in check-in, 403 access control, cgroups sandboxing, and captive portal bridge.
- Priority scheduling and preemption rules.

### Run End-to-End Design Smoke Tests (Playwright)
```bash
./venv/bin/pytest tests/design-smoke/ -v
```

---

## 7. Pre-Seeded User Accounts

| Role | Roll Number / Username | Password | Notes |
|---|---|---|---|
| **Admin** | `admin` | `admin123` | System Administrator / Lab Manager |
| **Faculty** | `faculty01` | `faculty123` | Dr. Alan Turing (CSE Department) |
| **Club Lead** | `club_gdg` | `club123` | Google Developer Student Club Lead |
| **Student** | `STU001` | `stu123` | Alice Johnson (CSE 2026) |
| **Student** | `STU002` | `stu123` | Bob Smith (SE 2026) |
| **Student** | `STU003` | `stu123` | Charlie Brown (AI 2027) |
| **Student** | `STU004` | `stu123` | Diana Prince (CSE 2026) |
| **Student** | `STU005` | `stu123` | Ethan Hunt (AI 2025) |
