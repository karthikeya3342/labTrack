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
1. **Lab 1: Computing Lab (`COMP-PC-01` to `COMP-PC-20`)**: 20 general computing PCs with Intel Core i7-13700, 32GB RAM.
2. **Lab 2: Software Engineering Lab (`SE-PC-01` to `SE-PC-15`)**: 15 development workstations with Intel Core i7-14700, NVIDIA T1000 GPUs, 32GB RAM.
3. **Lab 3: AI & High-Performance Lab (`AI-PC-01` to `AI-PC-10`)**: 10 high-performance workstations with AMD Ryzen 9 7950X, NVIDIA GeForce RTX 4090 24GB VRAM, 64GB RAM.

---

## 2. Research Paper Implementation (Chao He & Shi Cheng 2025)

The scheduling engine (`backend/app/core/intelligent_scheduler.py`) implements:

### Hard Constraints ($M_1 \dots M_6$)
- **$M_1$**: No student assigned to multiple lab sessions simultaneously.
- **$M_2$**: No instructor teaching multiple classes simultaneously.
- **$M_3$**: Full scheduled course coverage across required curriculum hours.
- **$M_4$**: Class cohort co-scheduling without fragmented cohort splits.
- **$M_5$**: Lab capacity compliance: $X(t_h, e_j) \le \text{Cap}(e_j)$ and specialized GPU hardware matching.
- **$M_6$**: Instructor availability schedule compliance.

### Soft Objectives ($f_1, f_2, f_3$)
- **$f_1$**: Time interval spacing between adjacent lab sessions for learning retention.
- **$f_2$**: High-capacity lab and specialized equipment matching (preventing GPU wastage for non-AI tasks).
- **$f_3$**: Even distribution of instructor lab teaching load.

### Variable Population Pyramid Model (VPPM) Genetic Algorithm
- Multi-population parallel evolution across 3 tiers (Apex Elite, Mid-tier crossover, Base Exploration).
- Periodic population confusion and migration between pyramid levels.
- Roulette wheel selection based on equipment cost adaptation:
  $$r_k = \sum f_k x_{ij}^t + \min \sum v_k x_{ij}^t, \quad p_k = \frac{n_k}{\sum n_k}$$

### Dynamic TaskPool Scheduler (Section 2.3)
- Default priority:
  $$P_{\text{default}} = \frac{1}{Q_{\text{time}} \cdot Q_{\text{res}}}, \quad Q_{\text{res}} = \sum w_i C_i$$
- Dynamic priority aging:
  $$P_{\text{task}} = P_{\text{default}} \cdot \left(1 + \frac{W_t}{\max(R_t, 1)}\right)$$
- **Preemption Rule**: Expensive GPU tasks must run at least 1 hour before being eligible for preemption by higher-priority queued tasks.

---

## 3. Workstation Agent & Captive Portal Bridge

### Workstation Lock Screen (`frontend/workstation_screen.html`)
- Boots into fullscreen kiosk mode.
- Polls `/api/pcs/<HOSTNAME>/lock-state` over the LAN switch.
- **HELD State**: Displays reserved student name, roll number, and dynamic 15-minute grace countdown. Any unauthorized student attempting to unlock is strictly rejected with:
  `"Access Denied: Workstation reserved for [Student Name]. Please use an available machine."`
- **AVAILABLE State**: Permits walk-ins with automated schedule backfilling up to 2 hours.
- **OCCUPIED State**: Shows active session dashboard with live CPU/RAM metrics and logout button.

### Captive Portal Auto-Authenticator Bridge
- Target URL: `https://10.10.10.2:8090/httpclient.html`
- When a student authenticates to unlock the PC, the agent sends an automated background POST:
  `mode=191&username=<roll_no>&password=<password>`
  granting instant campus internet access without requiring browser redirects.
- Upon logout, the agent sends a termination POST (`mode=193`) to prevent internet quota leakage.

### Linux Security & cgroups v2
- Creates isolated workspace sandbox in `/tmp/labtrack/workspace_<session_id>` with post-logout secure wipe (`shutil.rmtree`).
- Enforces cgroups v2 memory and CPU limits (`/sys/fs/cgroup/labtrack/session_<id>`).
- Reaps zombie/orphan child processes with `os.waitpid(-1, os.WNOHANG)`.
- Scans process tree for blacklisted binaries (miners: `xmrig`, `minerd`; torrents: `transmission`, `qbittorrent`; games: `steam`, `lutris`) and applies staged termination (`SIGTERM` $\to$ grace $\to$ `SIGKILL`).

---

## 4. Quick Start & Execution

### 1. Database Initialization
```bash
./scripts/setup_postgres.sh
```
Initializes PostgreSQL 16 cluster, applies `schema.sql` (with `btree_gist` GiST exclusion constraints), `procedures.sql`, `triggers.sql`, `indexes.sql`, and seeds all 45 workstations and users.

### 2. Start Backend Control Plane
```bash
./scripts/start_server.sh
# Listens on 0.0.0.0:8000
```
- Web Portal: `http://localhost:8000/`
- Workstation Kiosk Greeter: `http://localhost:8000/workstation/COMP-PC-01`
- OpenAPI Documentation: `http://localhost:8000/docs`

### 3. Run Automated Test Suite
```bash
pytest tests/test_mvp_flow.py -v
```
Verifies:
1. Workstation boot to `AVAILABLE`.
2. Advance booking state transition to `HELD` with metadata.
3. Unauthorized student 403 Forbidden rejection with strict message.
4. Reserved student unlock and telemetry ingestion.
5. Student logout and restoration to `AVAILABLE`.
6. Research Paper GA Simulation proving +16.3% to +34.6% equipment utilization gains over FCFS.
7. Agent daemon workspace sandbox creation and secure post-session wipe.

### 4. Start Client Workstation Agent
```bash
export LABTRACK_SERVER_URL=http://<SERVER_LAN_IP>:8000
export LABTRACK_HOSTNAME=COMP-PC-01
./scripts/start_agent.sh
```

### Pre-Seeded User Accounts
| Role | Roll Number / Username | Password | Notes |
|---|---|---|---|
| Admin | `admin` | `admin123` | System Administrator |
| Faculty | `faculty01` | `faculty123` | Dr. Alan Turing (CSE) |
| Student | `STU001` | `stu123` | Alice Johnson (CSE 2026) |
| Student | `STU002` | `stu123` | Bob Smith (SE 2026) |
| Student | `STU003` | `stu123` | Charlie Brown (AI 2027) |
| Student | `STU004` | `stu123` | Diana Prince (CSE 2026) |
| Student | `STU005` | `stu123` | Ethan Hunt (AI 2025) |
