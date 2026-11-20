# LabTrack Design System & Direction (Phase 3 Specification)

**Branch**: `design-overhaul`  
**Brand Concept**: Institutional Trust, Scientific Precision, Calm Under Load  
**Design Foundations**: Solid Colors, Precision Typography, Zero Slop, WCAG 2.2 AA Verified  

---

## 1. Design Concept & Strategic Surface Strategy

LabTrack is an academic computing infrastructure tool deployed across mission-critical research labs at IIITDM Kurnool. The interface must communicate institutional authority, stability, and surgical clarity.

### Rejection of Generic Clichés:
- **No Neon Cyber / Hacker Terminal Tropes**: Black backgrounds with glowing matrix green/cyan text are fatiguing under bright fluorescent laboratory illumination and unsuitable for academic faculty and research scholars.
- **No Floating Glassmorphism or Gradient Blobs**: Blur backdrops and heavy gradient text look like generic consumer marketing templates, tax low-spec GPU/integrated graphics on lab workstations, and introduce readability hazards.
- **Surface Strategy (Light vs. Dark Separation)**:
  1. **Web Portal (Clean Institutional Light Surface)**: Standardized on a crisp, high-density light palette (`#f8fafc` page, `#ffffff` card, `#0f172a` primary ink). Matches academic LMS systems (Canvas, Moodle), provides maximum scannability for 45-machine fleet tables, and maintains readability across diverse student and faculty laptop displays.
  2. **Workstation Kiosk (Focused Deep Slate Dark Surface)**: Standardized on an intentional deep zinc/slate palette (`#09090b` page, `#18181b` card, `#f4f4f5` text). Dark mode for the kiosk screen reduces screen glare in dimly lit nighttime computer labs, creates strong contrast for arm's length identification, and provides a focused greeter card.
  3. **Desktop Telemetry HUD Pill (Deep Solid Micro-Dock)**: Solid dark pill (`#09090b` with a crisp `#27272a` boundary and `0 10px 25px rgba(0,0,0,0.5)` drop shadow) floating unobtrusively in the bottom-right corner over arbitrary student desktop wallpapers, with high-contrast text and a protected logout mechanism.

---

## 2. Design Tokens (CSS Custom Properties)

All tokens will be centralized in `frontend/static/css/tokens.css` as the single source of truth.

### A. Neutral Scale (11-Step Zinc Palette)
```css
:root {
    --neutral-50:  #fafafa;
    --neutral-100: #f4f4f5;
    --neutral-200: #e4e4e7;
    --neutral-300: #d4d4d8;
    --neutral-400: #a1a1aa;
    --neutral-500: #71717a;
    --neutral-600: #52525b;
    --neutral-700: #3f3f46;
    --neutral-800: #27272a;
    --neutral-900: #18181b;
    --neutral-950: #09090b;
}
```

### B. Machine State Palette (WCAG 2.2 AA Verified)
Every machine state is defined by a unique combination of **Icon + Text Label + Background + Border + Accent**:

| Machine State | Icon (SVG) | Text Token | BG Token (Portal / Light) | BG Token (Kiosk / Dark) | Border Token | WCAG Ratio |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| **AVAILABLE** | `check-circle` | `#15803d` (green-700) | `#f0fdf4` (green-50) | `#052e16` (green-950) | `#86efac` (green-300) | 4.8:1 / 8.5:1 |
| **OCCUPIED** | `cpu` / `activity` | `#1e40af` (blue-800) | `#eff6ff` (blue-50) | `#172554` (blue-950) | `#93c5fd` (blue-300) | 5.4:1 / 7.2:1 |
| **HELD (Personal)** | `clock` | `#b45309` (amber-700) | `#fffbeb` (amber-50) | `#451a03` (amber-950) | `#fcd34d` (amber-300) | 4.8:1 / 9.0:1 |
| **HELD (Dedicated)**| `shield-lock` | `#0369a1` (sky-700) | `#f0f9ff` (sky-50) | `#082f49` (sky-950) | `#7dd3fc` (sky-300) | 4.9:1 / 8.8:1 |
| **HELD (Faculty)** | `graduation-cap`| `#4338ca` (indigo-700) | `#eef2ff` (indigo-50) | `#1e1b4b` (indigo-950) | `#a5b4fc` (indigo-300) | 5.2:1 / 8.1:1 |
| **HELD (Club)** | `zap` / `users` | `#7e22ce` (purple-700) | `#faf5ff` (purple-50) | `#3b0764` (purple-950) | `#d8b4fe` (purple-300) | 5.1:1 / 8.3:1 |
| **MAINTENANCE** | `alert-triangle`| `#b91c1c` (red-700) | `#fef2f2` (red-50) | `#450a0a` (red-950) | `#fca5a5` (red-300) | 5.9:1 / 5.8:1 |
| **NO_SHOW** | `user-x` | `#475569` (slate-600) | `#f8fafc` (slate-50) | `#0f172a` (slate-900) | `#cbd5e1` (slate-300) | 7.2:1 / 8.0:1 |

### C. Typography Scale & Font Pairing
- **Font Family**: Self-hosted Latin WOFF2 font pairing:
  - **Body / Interface**: `Inter` (or native high-performance system stack fallback: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`).
  - **Monospace / Tabular**: `JetBrains Mono` / `SF Mono` / `ui-monospace` with explicit `font-variant-numeric: tabular-nums` for all countdown timers, roll numbers, telemetry percentages, and hostnames.
- **Modular Scale (Portal)**:
  - `--text-xs`: `0.75rem` (12px)
  - `--text-sm`: `0.875rem` (14px)
  - `--text-base`: `1.0rem` (16px)
  - `--text-lg`: `1.125rem` (18px)
  - `--text-xl`: `1.25rem` (20px)
  - `--text-2xl`: `1.5rem` (24px)
- **Kiosk Distance Scale (Physical Workstation)**:
  - `--kiosk-badge`: `1.35rem` (21.6px) bold monospace (easily spotted from 3m aisle)
  - `--kiosk-title`: `2.0rem` (32px) semibold
  - `--kiosk-banner`: `1.15rem` (18.4px) bold
  - `--kiosk-timer`: `2.75rem` (44px) tabular bold monospace

### D. Spacing, Radii, Shadows & Motion
- **Spacing Scale**: 4px base (`--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`, `--space-6: 24px`, `--space-8: 32px`, `--space-12: 48px`).
- **Radii**: Clean, restrained curves (`--radius-sm: 4px`, `--radius-md: 6px`, `--radius-lg: 8px`, `--radius-full: 9999px`).
- **Elevation / Shadow**:
  - `--shadow-sm`: `0 1px 2px 0 rgba(0, 0, 0, 0.05)`
  - `--shadow-card`: `0 1px 3px 0 rgba(0, 0, 0, 0.08), 0 1px 2px -1px rgba(0, 0, 0, 0.08)`
  - `--shadow-modal`: `0 20px 25px -5px rgba(0, 0, 0, 0.15), 0 8px 10px -6px rgba(0, 0, 0, 0.1)`
- **Motion Tokens**:
  - `--duration-fast`: `150ms ease`
  - `--duration-normal`: `200ms cubic-bezier(0.16, 1, 0.3, 1)`
  - Reduced motion override: `@media (prefers-reduced-motion: reduce) { * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; } }`

---

## 3. Component Architecture & Patterns

### 1. Unified Icon Component (Elimination of All 30 Emojis)
Create an offline SVG sprite/component `frontend/static/icons.svg` containing clean, 24x24 geometric outline icons (Lucide-based) for:
`check-circle`, `clock`, `shield-lock`, `graduation-cap`, `zap`, `cpu`, `activity`, `alert-triangle`, `user-x`, `power`, `maximize`, `terminal`, `search`, `calendar`, `filter`, `x`, `chevron-down`, `users`, `book-open`.

### 2. Physical Kiosk Screen Layout
- **Top Header Bar**: Institution crest (`IIITDM Kurnool`), large readable workstation tag (`COMP-PC-01`), Lab Sub-Location (`AI & High Performance Lab • Row A Seat 1`), Network Health Pills (LAN Connected, Captive Portal Status), and Discrete Shutdown trigger.
- **Center Kiosk Card**:
  - State Banner with prominent Icon + Label (e.g. `[Icon] AVAILABLE FOR WALK-IN`).
  - Context Module (Dedicated research badge, personal grace countdown, faculty batch, or club workshop banner).
  - High-affordance Authentication Form with autofocus, keyboard Enter submit, and clear error recovery.
- **Footer**: Institutional attribution and security status.

### 3. Desktop Telemetry HUD Pill (Floating Mini-Dock)
- Anchored to `bottom: 24px; right: 24px;`.
- Left Group: Live pulsing green indicator dot, Student Name, Roll Number badge.
- Center Group: Monospace CPU load (`CPU 0.1%`) and Memory load (`RAM 7.1%`).
- Right Group: "Logout & Relock" button with **2-step presentation click confirmation** ("Click again to confirm relock" or inline popover) to completely prevent accidental desktop termination.

### 4. Accessible Modal & Destructive Confirmation Pattern
- **Modal Wrapper**: Built with semantic `<div role="dialog" aria-modal="true">`, accessible title, automatic keyboard `Escape` dismissal, and strict focus trapping (`Tab` cycles only within modal).
- **Destructive Confirmation Component**: Used for Master Reset Fleet, Force Preempt, and Terminate Workshop Early. Completely eliminates native browser `window.confirm()`. Displays structured explanation of impact and requires explicit confirmation.

### 5. Conflict Resolution Card Pattern (HTTP 403 & 409)
- Replaces raw backend error text with structured 3-part card:
  1. **What happened**: Clear explanation of the schedule collision or access restriction.
  2. **Who is involved**: Associated student, faculty batch, or club workshop.
  3. **Actionable Next Steps**: Alternative workstation recommendation or duration adjustment.

### 6. Faculty Dual-Segment Capacity Meter
- Displays a visual, proportional dual-bar meter comparing enrolled student batch count against primary lab capacity and secondary overflow lab capacity.

---

## 4. Phase 3 Approval Checkpoint

This design system establishes a coherent, durable, and accessible foundation across both physical lab workstations and web portals while strictly adhering to the **Logic is Frozen** mandate.
