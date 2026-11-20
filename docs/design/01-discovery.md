# LabTrack Design Discovery Report (Phase 1 Baseline)

**Date**: November 20, 2026  
**Branch**: `design-overhaul`  
**System**: Campus Computer Lab Management System (LabTrack)  
**Baseline Verification**: 34 Backend Unit & Integration Tests Passing • 5 Playwright Critical Flow Smoke Tests Passing  

---

## 1. Executive Summary & Architecture Map

LabTrack manages 45 physical workstations distributed across academic campus laboratories (AI & High Performance Lab, Systems Lab, Computing Lab, and Hardware/Embedded Lab). The application consists of two distinct frontend surfaces operating over a single unified FastAPI backend (Python 3.12, PostgreSQL 16, Linux cgroups v2 sandbox daemon):

1. **Kiosk Surface (`frontend/workstation_screen.html`)**:
   - Rendered on physical workstation displays at arm's length (50cm to 3m distance) in fullscreen kiosk mode.
   - Built with vanilla HTML5, CSS3, and JavaScript, animated using Anime.js (`/static/js/anime.min.js`).
   - Interacts with both the central API (`/api/pcs/{HOSTNAME}/lock-state`, `/api/agent/checkin`, `/api/agent/close`) and the local workstation system daemon (`http://127.0.0.1:8008/unlock`, `/lock`, `/poweroff`).
   - Features a persistent locked greeter card that transforms into a minimized floating telemetry HUD pill dock (`#floatingBarWidget`) over the student's active Linux desktop upon successful login.

2. **Web Portal Surface (`frontend/index.html`)**:
   - Role-based portal accessed via browser from student laptops, faculty computers, and lab admin workstations.
   - Built with offline-vendored React 18, ReactDOM 18, and in-browser Babel transpilation (`/static/js/babel.min.js`), animated with Anime.js and Motion.dev (`/static/js/motion.umd.js`).
   - Dynamically renders navigation tabs, capacity meters, multi-step booking forms, admin reservation modals, and fleet status grids based on authenticated JWT session roles (`student`, `faculty`, `club_lead`, `admin`).

```
                    ┌────────────────────────────────────────────────────────┐
                    │                   LabTrack Ecosystem                   │
                    └────────────────────────────────────────────────────────┘
                                               │
             ┌─────────────────────────────────┴─────────────────────────────────┐
             ▼                                                                   ▼
┌───────────────────────────────┐                               ┌───────────────────────────────┐
│     Kiosk Surface (PC)        │                               │      Web Portal (Browser)     │
│  workstation_screen.html      │                               │          index.html           │
│  (Vanilla JS + Anime.js)      │                               │  (React 18 + Babel + Motion)  │
└───────────────────────────────┘                               └───────────────────────────────┘
  │ Fullscreen locked greeter                                     │ Role-based navigation
  │ 7+ machine states                                             │ Live Fleet Grid (Guest/User)
  │ Desktop floating HUD pill                                     │ Student Booking & Algorithms
  │ Local daemon calls (:8008)                                    │ Faculty Extra Labs & Sessions
                                                                  │ Club Hackathon Proposals & Roster
                                                                  │ Admin Dedicated Holds & Fleet Reset
             │                                                                   │
             └─────────────────────────────────┬─────────────────────────────────┘
                                               ▼
                               ┌───────────────────────────────┐
                               │     FastAPI Backend (:8000)   │
                               │  PostgreSQL 16 Database       │
                               │  cgroups v2 Sandboxing        │
                               └───────────────────────────────┘
```

---

## 2. File & Component Inventory

| File Path | Size / Lines | Technologies | Purpose / Roles Served | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `frontend/workstation_screen.html` | 661 lines (19 KB) | HTML5, Vanilla JS, Anime.js | Fullscreen workstation lock screen, machine state greeter, desktop telemetry HUD dock | `workstation.css`, `anime.min.js`, `/static/iiitk.jpeg` |
| `frontend/static/css/workstation.css` | 799 lines (17.6 KB) | Plain CSS3 | Styling for workstation kiosk cards, state banners, context boxes, power triggers, HUD pill | Native CSS custom properties |
| `frontend/index.html` | 3,469 lines (149 KB) | React 18, Babel, Motion.dev | Web portal single-page application with role tabs and modals | `react.production.min.js`, `react-dom.production.min.js`, `babel.min.js`, `portal.css`, `iiitk.jpeg` |
| `frontend/static/css/portal.css` | 1,381 lines (32.6 KB) | Plain CSS3 | Styling for web portal navigation, fleet grid cards, forms, stat strips, modals | Native CSS custom properties |
| `frontend/static/dev_states.html` | 512 lines (43.8 KB) | HTML5, Plain CSS | Dev-only state preview harness rendering all 13 machine and modal states in isolation | `workstation.css`, `portal.css` |
| `frontend/static/js/*` | 5 vendored bundles | Pre-minified JS | React 18, ReactDOM 18, Babel 7, Anime.js 3, Motion.dev UMD | Zero external CDN requests |
| `frontend/static/clubs/*` | 15 image assets | PNG, SVG, JPEG | High-resolution logos for campus clubs (DataWorks, Robotics, BitSquad, GDG, Electronix) | Local filesystem |

### React Component Hierarchy (`frontend/index.html`):
- `App`: Main shell holding auth state, current role, active navigation tab, global polling (5-second cadence), and flash notification banner.
  - `AuthModal`: Unified modal for logging in as Student, Faculty, Club Lead, or Lab Administrator.
  - `TabLiveGrid`: Real-time interactive fleet inspector showing 45 workstations with state chips, lab filters, and machine specs.
  - `TabBooking`: Multi-parameter student workstation reservation form with algorithm selection (FCFS, Priority Aging, Genetic Algorithm).
  - `TabMyReservations`: Personal reservation history, active claim timers, and cancelation controls.
  - `TabFaculty`: Extra lab request workflow with cohort enrollment inspector and secondary overflow lab selector.
  - `TabScheduledSessions`: Practical lab monitor displaying live attendance, assigned workstations, and "Release Lab Early" trigger.
  - `TabClubs`: Technical club event proposal creation form and live workshop roster monitor.
  - `TabAdmin`: Executive statistics strip, Pending Club Proposals approval queue, Active Dedicated Holds manager, Extend Reservation modal, Reserve PC for Student modal, and Master Fleet Reset action.

---

## 3. Screen & State Inventory

All baseline BEFORE screenshots have been captured across viewports and stored in `before/kiosk/` and `before/portal/`:

### Surface A: Kiosk Screen States (`before/kiosk/`)
1. **AVAILABLE (`kiosk-available-1920x1080.png`, `1366x768.png`)**:
   - Green banner (`banner-AVAILABLE`), host badge `COMP-PC-01`, lab name `Computing Lab`, LAN connected chip, WAN locked chip, unified login form (Roll Number + Password).
2. **HELD - Personal Advance Booking**:
   - Amber banner (`banner-HELD`), student name and roll, 15-minute grace countdown timer (`#graceCountdown`), notice regarding auto-cancellation as `NO_SHOW`.
3. **HELD - Admin Dedicated Allocation (`kiosk-held-dedicated-1920x1080.png`, `1366x768.png`)**:
   - Golden locked banner, purpose tag (e.g. "Final Year Project / Research"), project title, date window (e.g. "Nov 20, 2026 – Dec 20, 2026"), and human countdown ("28 days remaining").
4. **HELD - Faculty Practical Lab**:
   - Course name, cohort batch (e.g. "CSE-301 Section A"), faculty instructor name, session topic, and student check-in form.
5. **HELD - Club Event Takeover**:
   - Custom club branding (emblem logo, theme banner), event title ("Deep Learning Sprint"), description, and attendee roll check-in.
6. **OCCUPIED - Active Sandboxed Session (`kiosk-occupied-1920x1080.png`, `1366x768.png`)**:
   - Unlocked state, active student name, session ID, real-time CPU & RAM load metrics, "Minimize & Open Linux Desktop" button, and "Logout & Relock Workstation" button.
7. **MAINTENANCE - Hardware Diagnostic Lockout (`kiosk-maintenance-1920x1080.png`, `1366x768.png`)**:
   - Red diagnostic lockout banner, diagnostic reason badge (e.g. "RAM diagnostics in progress"), advisory to use adjacent machine.
8. **ACCESS DENIED - Collision/Security Rejection**:
   - Red warning alert box when an unauthorized student attempts login on an exclusively held workstation.
9. **DESKTOP TELEMETRY HUD PILL (`kiosk-hud-floating-1920x1080.png`, `1366x768.png`)**:
   - Compact floating dark mini-dock rendered over the active Linux desktop in the bottom-right corner. Displays live green dot, user roll badge, host tag, CPU%, RAM%, and red "Logout & Relock" button.

### Surface B: Web Portal Views (`before/portal/`)
1. **Guest / Public Fleet Grid (`portal-grid-guest-desktop-1920.png`, `laptop-1280.png`, `tablet-768.png`, `mobile-375.png`)**:
   - 45-workstation interactive card grid filterable by lab and state.
2. **Student Booking & My Reservations (`portal-student-booking-laptop.png`, `portal-student-reservations-laptop.png`)**:
   - Lab selection, time window, task type, software packages checkboxes, allocation engine selector, and reservation card list.
3. **Faculty Extra Labs & Scheduled Sessions (`portal-faculty-extralabs-laptop.png`, `portal-faculty-scheduled-laptop.png`)**:
   - Course and batch capacity inspector, secondary overflow lab assignment, and live lab session monitor.
4. **Technical Clubs Lead Portal (`portal-clubs-lead-laptop.png`)**:
   - Club event proposal submission, live check-in roster, and workshop termination.
5. **Admin Operations Dashboard & Reserve PC Modal (`portal-admin-dashboard-desktop-1920.png`, `laptop-1280.png`, `portal-admin-reserve-modal-desktop-1920.png`, `laptop-1280.png`)**:
   - 5-metric executive statistics strip, student autocomplete modal, quick-extend pills (+5d, +1w, +1m), custom extend modal, and master system reset button.

---

## 4. End-to-End User Flow Maps & Error Paths

### Flow A: Student Walk-In (Kiosk & Portal)
```
[Student at PC] ──> Sees AVAILABLE Banner ──> Enters Roll & Password
                          │
                          ▼
                  POST /api/agent/checkin
                          │
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
 [200 OK: session_id]              [401 / 403 / 409 / 503]
        │                                   │
        ▼                                   ▼
 Calls local daemon:               Displays Inline Error:
 GET :8008/unlock?session_id=...   - 401: Invalid password
        │                          - 403: Held for another student
        ▼                          - 409: Active session exists
 Workstation unlocks to            - 503: Machine under maintenance
 Linux Desktop + HUD Pill
```

### Flow B: Student Advance Booking (Portal)
```
[Student in Portal] ──> Selects Lab, Window, Task Type, Software, Algorithm
                                │
                                ▼
                    POST /api/reservations/advance
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
 [200 OK: Assigned PC]                           [409 Conflict]
        │                                               │
        ▼                                               ▼
 Workstation enters HELD state;                  Displays Conflict Reason:
 Starts 15-minute grace countdown                - No machines match software
 on physical kiosk display                       - Overlaps existing reservation
                                                 - Advance window limit reached
```

### Flow C: Admin Dedicated Allocation (Portal -> Kiosk)
```
[Admin in Portal] ──> Opens "+ Reserve PC for Student" Modal
                                │
   - Types Roll/Name ──> GET /api/admin/students/search?q=... (Autocomplete)
   - Selects Duration Preset (+5 Days, +1 Wk, +1 Mo) or Custom
   - Chooses Academic Purpose (FYP / Research / Contest)
   - Enters Project Title & Remarks
   - Chooses Auto-Assign or Specific PC
   - Sets "Force Preempt" if needed
                                │
                                ▼
                 POST /api/admin/reservations/dedicated
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
 [200 OK: Dedicated Res]                         [409 Conflict]
        │                                               │
        ▼                                               ▼
 Physical Workstation locks to                   Modal shows conflict details:
 ADMIN DEDICATED ALLOCATION state:               - Student has active dedicated hold
 Displays Purpose badge, Project title,          - PC reserved for club / faculty
 Date window, and Human countdown                - Preemption requires confirmation
 ("28 days remaining").
 Persists across logouts!
```

### Flow D: Faculty Extra Labs (Portal -> Kiosk)
```
[Faculty in Portal] ──> Enters Course, Batch, Topic, Enrolled Count
                                │
   - Capacity Inspector compares Enrolled Count vs Primary Lab Seats
   - If Enrolled > Capacity: Enforces Secondary Overflow Lab selection
   - Chooses Immediate Lab Start or Scheduled Time
                                │
                                ▼
                 POST /api/faculty/reserve-extra-lab
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
 [200 OK: Session Created]                       [409 Conflict]
        │                                               │
        ▼                                               ▼
 Target workstations across labs                 Error Banner:
 lock to FACULTY PRACTICAL LAB state.            - Insufficient combined seats
 Scheduled Sessions tab displays live            - Overlaps dedicated / club hold
 attendance roster.
```

### Flow E: Technical Clubs & Hackathons (Portal -> Kiosk)
```
[Club Lead in Portal] ──> Submits Event Proposal (Club, Title, Date, Seats)
                                │
                                ▼
                     Status: PENDING Approval
                                │
   [Admin in Operations] ──> Reviews Proposal Queue
   - Clicks Approve (or Reject with feedback)
                                │
                                ▼
   When scheduled time arrives:
   All workstations in selected lab lock to CLUB TAKEOVER mode
   (Branded banner, logo, workshop title, roll check-in).
   Club Lead monitors live roster in portal.
   Can trigger "End Workshop Early" (Releases all PCs back to walk-in).
```

### Flow F: Fleet Health, Maintenance & Master Fleet Reset
```
[Admin in Portal] ──> Views Executive Stats & Fleet Grid (45 PCs)
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
 [Filter Fleet]         [Toggle Maintenance]    [Master System Reset]
 - By Lab               - Calls:                - Destructive Action
 - By State               POST /api/admin/pcs/  - Immediate confirmation
 - Search host            {id}/maintenance        required
                        - Machine displays      - Calls:
                          offline diagnostic      POST /api/admin/system/
                          warning screen          release-all
                                                - Unlocks all 45 PCs
                                                  to AVAILABLE walk-in
```

---

## 5. Styling Inconsistency & Code Smells Inventory

### A. Hardcoded Color Proliferation
A comprehensive regex extraction revealed **70 unique hardcoded hex colors** and **19 unique rgba strings** across CSS and inline HTML styles. Major inconsistencies include:
- 11 distinct shades of blue: `#0284c7`, `#1d4ed8`, `#1e1b4b`, `#1e40af`, `#2563eb`, `#38bdf8`, `#3b82f6`, `#60a5fa`, `#93c5fd`, `#bfdbfe`, `#dbeafe`.
- 9 distinct shades of green: `#052e16`, `#059669`, `#065f46`, `#15803d`, `#166534`, `#16a34a`, `#22c55e`, `#4ade80`, `#86efac`.
- 10 distinct shades of amber/orange: `#451a03`, `#78350f`, `#92400e`, `#b45309`, `#d97706`, `#f59e0b`, `#fbbf24`, `#fcd34d`, `#fde68a`, `#fef3c7`.
- 12 distinct shades of red/rose: `#450a0a`, `#7f1d1d`, `#991b1b`, `#9f1239`, `#b91c1c`, `#dc2626`, `#e11d48`, `#ef4444`, `#f87171`, `#fca5a5`, `#fee2e2`, `#fef2f2`.
- Lack of a standardized neutral scale: `#09090b`, `#0c0c0e`, `#0f172a`, `#121215`, `#18181b`, `#1e293b`, `#27272a`, `#334155`, `#3f3f46`, `#475569`, `#52525b`, `#64748b`, `#71717a`, `#94a3b8`, `#a1a1aa`, `#cbd5e1`, `#e2e8f0`, `#f1f5f9`, `#f4f4f5`, `#f8fafc`.

### B. Inline Style Sprawl
- Over 85 elements in `frontend/index.html` and `frontend/workstation_screen.html` use extensive inline `style="..."` attributes for layout, typography, and status styling rather than reusable component classes.
- Modal backdrops, header blocks, and error message containers have duplicate CSS definitions between `portal.css` and `workstation.css`.

### C. Complete Emoji Inventory (30 Unique Emojis to be replaced by SVG Icons)
1. 🟢 `AVAILABLE` workstation state indicator
2. ⏳ `HELD` / Grace period countdown / pending indicator
3. ⚡ `OCCUPIED` / Active computing session indicator
4. ⚠️ `MAINTENANCE` / Diagnostic warning
5. 🔒 Dedicated workstation hold / Lock indicator
6. 🔓 Unlock workstation action
7. 🔬 Final Year Project / Research academic purpose
8. 🎓 Faculty session / Academic coursework purpose
9. 🚀 Technical Club / Hackathon event takeover
10. 🎟 Event ticket / Workshop check-in
11. ⏻ Workstation power off / shutdown
12. 💻 Linux Desktop minimization trigger
13. 💡 Keyboard shortcut tip
14. 🚨 Master Fleet Reset destructive emergency action
15. 🛑 Emergency halt indicator
16. 📋 Roster / Proposals review list
17. 📝 Written feedback / Remarks field
18. 📅 Date window / Schedule picker
19. 🔄 Refresh / Polling indicator
20. 🔍 Search / Fleet inspector filter
21. 👥 Cohort / Student group indicator
22. 👨 Faculty instructor indicator
23. 🏛 IIITDM Kurnool institution header
24. 🏫 Academic laboratory selector
25. 🎯 Capstone project indicator
26. 🏆 Competitive programming purpose
27. 🖥 Physical workstation icon
28. ⚖ Algorithm selection indicator
29. ⚙ Settings / System operations
30. ✓ Success / Completed state mark

---

## 6. Phase 1 Sign-Off

Phase 1 discovery is complete. All 22 baseline screenshots are archived in `before/`, all user flows and error paths are fully mapped, all hardcoded styling and emojis have been cataloged, and the dev preview harness (`/static/dev_states.html`) is live and verified.
