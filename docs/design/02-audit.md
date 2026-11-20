# LabTrack UX + UI Audit Report (Phase 2)

**Evaluators**: Principal Product Designer, UX Researcher, Design Systems Engineer, Front-End Engineer, Accessibility Specialist  
**Target Systems**: Physical Workstation Kiosk (`frontend/workstation_screen.html`), Web Portal (`frontend/index.html`)  
**Standard**: Shipped-Product Standard • WCAG 2.2 Level AA Compliance • Nielsen Norman Group 10 Usability Heuristics  

---

## 1. Executive Summary & Audit Methodology

The LabTrack interface was audited across 12 specific evaluation lenses using automated tooling (`axe-core-python`, headless Chromium, custom WCAG 2.2 contrast analyzer `scripts/contrast_checker.py`), distance legibility testing (simulating arm's length 50cm to 3m lab viewports), and multi-viewport inspection (375px mobile, 768px tablet, 1280px laptop, 1920px desktop).

### Key Audit Findings:
1. **Severe Distance Contrast Failures on Kiosk**: Sub-labels (`#labNameDisplay`), footer metadata, and input labels fail WCAG AA contrast against `#09090b` / `#0c0c0e`, rendering them unreadable at 2–3 meters under lab lighting.
2. **State System Ambiguity**: Machine states currently rely on loose emojis (🟢, ⏳, ⚡, ⚠️) and non-standardized colors. Dedicated 30-day research allocations and 15-minute walk-in holds look visually identical in portal fleet grids.
3. **Safety Hazards on Destructive Admin Actions**: High-consequence operations (Master Fleet Reset, Terminate Workshop Early, Force Preempt) rely on native browser `window.confirm()` dialogs, which are prone to accidental keystroke confirmation.
4. **Layout Jitter in Countdowns**: Grace and session countdowns lack tabular numerals (`font-variant-numeric: tabular-nums`), causing 1–2px horizontal layout shifting on every second tick.
5. **Axe Violations on Portal & Kiosk**: 63 color-contrast violations on portal cards, missing `<h1>` headings, absence of `<main>` landmarks, and lack of focus trapping on modal dialogs.

---

## 2. In-Depth Lens Analysis

### Lens 1: Kiosk Legibility at Distance (Arm's Length to 3 Meters)
- **Host Identifier Size**: In `frontend/workstation_screen.html` (line 102), `.host-badge` is styled at `0.95rem` (15.2px) inside `#hostBadge`. In a physical lab room with 45 PCs, students walking down an aisle cannot identify machine hostnames (e.g. `COMP-PC-14` vs `COMP-PC-24`) without leaning over the monitor.
- **Contrast of Sub-Labels**: `#labNameDisplay` ("Computing Lab • Row A Seat 1") uses color `#71717a` over `#0c0c0e`, giving a contrast ratio of **4.04:1** (fails WCAG AA 4.5:1 threshold; verified by `scripts/contrast_checker.py` and Axe).
- **Reliance on Color**: The status banner relies on emoji and green/amber/red backgrounds. In greyscale or for color-blind users (deuteranopia), the banners lack distinct structural icons and high-contrast typography.

### Lens 2: State System Coherence Across Surfaces
- The system manages 8 distinct machine states (`AVAILABLE`, `HELD-Personal`, `HELD-Dedicated`, `HELD-Faculty`, `HELD-Club`, `OCCUPIED`, `MAINTENANCE`, `NO_SHOW`).
- In `frontend/static/css/workstation.css`, states use dark saturated backgrounds (`#052e16`, `#451a03`, `#1e1b4b`, `#450a0a`), whereas in `frontend/static/css/portal.css`, states use light pastel cards (`#f0fdf4`, `#fffbeb`, `#fef2f2`, `#f8fafc`).
- In the portal grid (`.pc-card`), admin dedicated multi-week holds display the generic label "HELD" with an amber badge, failing to convey that the machine is permanently assigned for research and cannot be booked by walk-ins.

### Lens 3: Time & Countdown Communication
- **Tabular Numerals**: On Kiosk `#graceCountdown` (line 218), digits `14:59` animate down every second. Proportional fonts cause character width jitter between `1` (narrow) and `0` (wide).
- **Timezone Clarity**: Dedicated allocations display `Nov 20, 2026 – Dec 20, 2026` without specifying expiration time or timezone (e.g. `23:59 IST`).
- **Urgency Escalation**: The grace timer uses `#fbbf24` (amber) whether 14 minutes remain or 15 seconds remain. It lacks progressive urgency escalation (e.g. shifting to a warning pulse when `< 2 minutes` remain).

### Lens 4: Error Clarity & Conflict Resolution (HTTP 403 & 409)
- **Workstation Kiosk 403**: When a student tries to log into a workstation reserved for another peer, `showMessage(data.detail, 'error')` displays `Workstation strictly held for Alice Johnson (STU001)` in a plain red box. It does not inform the user which lab has available machines or provide an actionable next step.
- **Portal 409 Conflicts**: If an admin dedicates a PC that collides with a scheduled club workshop, or if a student books an overlapping slot, the portal triggers an untyped alert banner. It does not display a structured conflict card detailing *What happened*, *Who is involved*, and *Resolution options*.

### Lens 5: Student Task Speed & Input Ergonomics
- **Lack of Autofocus**: When the kiosk screen transitions to `AVAILABLE`, `#loginRollInput` is not focused automatically. A walk-in student must reach for the mouse to click into the roll number field before typing.
- **Focus Rings**: Input focus rings in `workstation.css` (`--border-focus: #3b82f6`) lack an outer offset ring, making focus indicators invisible against dark input backgrounds.

### Lens 6: Admin Density & Operational Safety
- **Destructive Actions Guardrails**:
  - `Master Reset Fleet to Walk-in Mode` calls native `window.confirm()`.
  - `End Workshop Early` calls native `window.confirm()`.
  - `Release Dedicated Reservation` calls native `window.confirm()`.
  - Native browser confirm dialogs are a major anti-pattern in mission-critical operations because a stray keystroke (Enter/Space) immediately executes irreversible actions.
- **Force Preempt Risk**: In the `+ Reserve PC for Student` modal, the "Force Preempt" checkbox immediately terminates any active student session upon form submission without a secondary verification summary.

### Lens 7: Forms & Capacity Inspectors
- **Faculty Capacity Inspector**: In `TabFaculty`, when enrolled batch count exceeds primary lab capacity (e.g. 45 students in a 25-seat lab), the secondary overflow lab dropdown is exposed, but there is no visual breakdown of seat distribution.
- **Autocomplete Accessibility**: The live student search combobox in the Reserve PC modal lacks ARIA combobox attributes (`role="combobox"`, `aria-autocomplete="list"`, `aria-expanded`), leaving screen reader users unaware of matching dropdown items.

### Lens 8: Desktop Telemetry HUD (Arm's Length Mini-Dock)
- **Accidental Click Hazard**: In `#floatingBarWidget`, the red `Logout & Relock` button is positioned immediately next to telemetry chips without a confirmation dialog or safety margin.
- **Legibility**: Telemetry chips (`CPU 0.1%`, `RAM 7.1%`) use `#71717a` text, which struggles for legibility over light-colored student desktop wallpaper behind the dock.

### Lens 9: Role-Based Navigation & View State
- When a user logs out from `admin` or `faculty` role, the active tab state is not cleanly reset to `grid`, resulting in empty tab views for newly authenticated student sessions.
- Navigation bar lacks a persistent indicator of current network connectivity status.

### Lens 10: Microcopy & Tone
- Inconsistent terminology across surfaces: "Unlock Workstation" vs "Check In" vs "Claim Workstation" vs "Log In".
- Overuse of alarming emojis: 🚨, ⚠️, 🛑 throughout operational dashboards creates unnecessary cognitive stress.
- Primary buttons in modals frequently say "Submit" instead of explicit, verb-led labels ("Confirm Dedicated Allocation", "Approve Workshop Proposal").

### Lens 11: Accessibility (WCAG 2.2 AA Compliance)
- **Automated Axe Violations**:
  - Kiosk: `color-contrast` (serious) on `#labNameDisplay` and `footer`; `landmark-one-main` (moderate) missing `<main>`; `page-has-heading-one` (moderate) missing `<h1>`; `region` (moderate).
  - Portal: `color-contrast` (serious, 63 nodes on `.pc-lab-sub` and status chips).
- **Modal Focus Trapping**: Neither `AuthModal`, `ReserveModal`, nor `ExtendModal` trap keyboard focus (`Tab` / `Shift+Tab` cycles behind the modal into background page content).
- **Reduced Motion**: Zero CSS rules handling `@media (prefers-reduced-motion: reduce)`.

### Lens 12: Nielsen Norman Group 10 Usability Heuristics Evaluation

| Heuristic | Rating (1-5) | Audit Assessment |
| :--- | :---: | :--- |
| **1. Visibility of System Status** | 3.5 / 5 | Good live telemetry and status banners, but countdowns lack tabular numerals and timezone clarity. |
| **2. Match Between System & Real World** | 4.0 / 5 | Institutional terminology matches academic lab workflows well. Emojis detract from professional tone. |
| **3. User Control & Freedom** | 2.5 / 5 | Destructive actions lack robust cancellation safeguards; HUD relock has no undo or confirmation. |
| **4. Consistency & Standards** | 3.0 / 5 | High color divergence (70 hex colors); differing status colors between portal and kiosk. |
| **5. Error Prevention** | 2.5 / 5 | Native browser confirms on Master Reset and Force Preempt fail error prevention standards. |
| **6. Recognition Rather than Recall** | 3.5 / 5 | Clear presets for duration (+5d, +1w, +1m), but faculty overflow lacks visual seat distribution. |
| **7. Flexibility & Efficiency of Use** | 3.5 / 5 | Good keyboard shortcuts noted in UI, but kiosk login input lacks autofocus. |
| **8. Aesthetic & Minimalist Design** | 3.0 / 5 | Cluttered emoji usage, excessive inline styles, inconsistent card paddings and border radii. |
| **9. Help Users Recognize & Recover from Errors**| 2.5 / 5 | 403 and 409 errors show technical detail without actionable guidance or alternative PC suggestions. |
| **10. Help & Documentation** | 3.5 / 5 | Clear instructions in dedicated reservation cards, but lacks structured empty states across tabs. |

---

## 3. Comprehensive Audit Issue Matrix

| Issue ID | Surface | Specific Issue | Precise Evidence | Severity | Proposed Fix |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AUD-01** | Kiosk | Low contrast on lab sub-header & footer | `#labNameDisplay` (`#71717a` on `#0c0c0e` = 4.04:1) & `footer` (`#52525b` = 2.57:1) | Critical | Update tokens to `#a1a1aa` (7.0:1) and `#71717a` to meet WCAG AA |
| **AUD-02** | Kiosk | Workstation Hostname too small for distance reading | `#hostBadge` is `0.95rem` (15.2px); unreadable across lab aisles | High | Increase to `1.35rem`, bold tabular font, high-contrast badge background |
| **AUD-03** | Kiosk | Layout jitter on grace timer ticks | `#graceCountdown` has proportional font; numbers shift 1-2px every second | Medium | Apply `font-family: var(--font-mono); font-variant-numeric: tabular-nums` |
| **AUD-04** | Kiosk | No autofocus on Roll Number input | `#loginRollInput` requires manual mouse click on load | Medium | Add `autofocus` attribute and JS `.focus()` on state change to AVAILABLE |
| **AUD-05** | Kiosk | Missing landmark structures and `<h1>` | Axe report: `landmark-one-main`, `page-has-heading-one`, `region` | High | Wrap kiosk card in `<main>`, add accessible hidden `<h1>`, use semantic tags |
| **AUD-06** | Kiosk | Raw 403 Access Denied without recovery guidance | `showMessage(data.detail, 'error')` outputs text without alternative advice | High | Present structured error card: Reason, Current Holder, "Find Available PC" link |
| **AUD-07** | HUD | Accidental click hazard on "Logout & Relock" | Single mouse click triggers immediate session termination | Critical | Wrap in presentation 2-step confirmation dialog before calling `handleLogout()` |
| **AUD-08** | HUD | Low contrast on telemetry chips over desktop wallpapers | `.dock-meta-row` uses `#71717a`; unreadable over bright desktop backgrounds | High | Enforce solid dark pill backdrop with `rgba(9,9,11,0.95)`, high-contrast chips |
| **AUD-09** | Portal | 63 color-contrast violations on fleet grid cards | Axe report: `.pc-lab-sub` (`#94a3b8` on `#ffffff` = 2.56:1); badge contrast | Critical | Replace with `#475569` text (6.2:1) and dark-bordered status pills |
| **AUD-10** | Portal | Destructive Master Fleet Reset uses native `confirm()` | Native `window.confirm()` in `index.html` line 3120 | Critical | Replace with custom accessible modal requiring typed confirmation "RESET FLEET" |
| **AUD-11** | Portal | Force Preempt checkbox lacks explicit safety warning | Checking box immediately dislodges active student upon form submit | High | Add visual warning alert inside modal summarizing displacement consequence |
| **AUD-12** | Portal | Unstructured 409 conflict feedback | Alert banner does not distinguish between room clash, student hold, or quota | High | Implement structured 409 Conflict Dialog: What happened, Who is involved, Options |
| **AUD-13** | Portal | Faculty capacity inspector lacks visual seat split | Shows secondary lab dropdown without split ratio of students per lab | Medium | Add visual dual-segment bar meter indicating seat allocation across labs |
| **AUD-14** | Portal | Modals lack focus trapping and Escape key handler | `Tab` key escapes modal into background; `Escape` does not dismiss | High | Implement focus trap helper and keyboard `Escape` dismissal listener |
| **AUD-15** | Both | 30 raw emojis used instead of professional icons | 🟢, ⏳, ⚡, ⚠️, 🚨, 🔬, 🎓, etc. undermine institutional aesthetic | High | Replace all emojis with vendored, unified SVG icons (Lucide-inspired) |
| **AUD-16** | Both | 70 hardcoded hex colors and 19 rgba values | Inconsistent color tokens and inline styles across all components | High | Consolidate into standardized CSS custom properties in `tokens.css` |
| **AUD-17** | Both | Absence of `prefers-reduced-motion` support | Animations run unconditionally, causing issues for motion-sensitive users | Medium | Add `@media (prefers-reduced-motion: reduce)` to disable transitions/transforms |

---

## 4. Prioritized Action Plan

1. **P0 (Blockers & Critical Safety/A11y)**:
   - Establish token foundation (`tokens.css`) solving all WCAG 2.2 AA contrast failures (AUD-01, AUD-08, AUD-09, AUD-16).
   - Implement custom confirmation modal for destructive operations (Master Reset AUD-10, Force Preempt AUD-11).
   - Add accidental-click protection to Kiosk Desktop HUD (AUD-07).
   - Vendor local fonts and SVG icon system, replacing all 30 emojis (AUD-15).

2. **P1 (Core UX & Accessibility Polish)**:
   - Fix kiosk distance readability: enlarge host badge, add tabular numerals to countdowns, add autofocus (AUD-02, AUD-03, AUD-04).
   - Implement semantic landmarks (`<main>`, `<h1>`, `<header>`) and modal focus trapping (AUD-05, AUD-14).
   - Implement structured 403/409 conflict dialogs (AUD-06, AUD-12).

3. **P2 (Design Polish & Consistency)**:
   - Add visual dual-segment capacity meter to Faculty Extra Labs (AUD-13).
   - Add `prefers-reduced-motion` fallbacks across all animation layers (AUD-17).
   - Align microcopy to institutional, verb-led voice across all buttons and states.
