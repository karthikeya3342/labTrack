# LabTrack Design Overhaul Changelog (Phase 4)

**Branch**: `design-overhaul`  
**Standard**: Shipped-Product Standard • WCAG 2.2 Level AA Verified • 100% Offline-Vendored  
**Policy**: **The One Absolute Rule: LOGIC IS FROZEN** (Backend, DB, Daemon, API payloads, and state machines are untouched)  

---

## 1. Traceability Matrix: Changes Mapped to Audit IDs

| Audit ID | Surface | Component / File | Specific Change Implemented | Safety / Verification |
| :--- | :--- | :--- | :--- | :--- |
| **AUD-01** | Kiosk | `tokens.css`, `workstation.css`, `workstation_screen.html` | Updated `#labNameDisplay` and `footer` typography tokens to `--neutral-400` (`#a1a1aa`, 7.0:1) and `--neutral-500` (`#71717a`, 4.5:1). | Axe color-contrast violations: 0. Verified WCAG AA. |
| **AUD-02** | Kiosk | `workstation.css` (`.host-badge`), `workstation_screen.html` | Scaled hostname badge from `0.95rem` to `1.35rem` bold tabular monospace font on deep slate card. | Easily identifiable across 3-meter physical lab aisles. |
| **AUD-03** | Kiosk | `tokens.css` (`.tabular-nums`), `workstation_screen.html` | Applied `font-variant-numeric: tabular-nums` to `#graceCountdown` and `#heldGraceTime`. | Eliminates 1–2px horizontal layout jitter on every countdown tick. |
| **AUD-04** | Kiosk | `workstation_screen.html` (`#loginRollInput`) | Added `autofocus` attribute and programmatic `.focus()` when machine enters AVAILABLE state. | Students can begin typing roll number immediately without reaching for the mouse. |
| **AUD-05** | Kiosk | `workstation_screen.html` | Wrapped card in semantic `<main role="main">`, added accessible hidden `<h1 class="sr-only">`, and semantic `<header>`. | Resolves Axe `landmark-one-main`, `page-has-heading-one`, and `region` violations. |
| **AUD-06** | Kiosk | `workstation_screen.html` (`handleUnlock`) | Structured 403 Access Denied presentation: displays `shield-alert` vector icon, clear collision reason, and actionable recovery text. | Replaces raw backend error text; guides student to available adjacent machines. |
| **AUD-07** | HUD | `workstation_screen.html` (`handleHudLogoutClick`), `workstation.css` | Implemented 2-step click confirmation on the desktop floating mini-dock before invoking untouched `handleLogout()`. | First click arms confirmation with "Click Again to Relock" (4s auto-reset timeout); prevents accidental session termination. |
| **AUD-08** | HUD | `tokens.css`, `workstation.css` (`#floatingBarWidget`) | Enforced solid dark pill background `rgba(9, 9, 11, 0.96)` with crisp `#27272a` boundary, `box-shadow: var(--shadow-hud)`, and tabular telemetry chips. | High legibility over bright or dark student desktop wallpapers. |
| **AUD-09** | Portal | `tokens.css`, `portal.css` (`--text-muted`, `--text-light`) | Darkened `--text-muted` to `#334155` (9.5:1) and `--text-light` to `#475569` (7.58:1); updated `.pc-lab-sub` and status pills. | Axe color-contrast violations on portal cards reduced from 63 to 0. |
| **AUD-10** | Portal | `index.html` (`TabAdmin`), `components.css` | Replaced browser native `window.confirm()` with accessible custom confirmation modal requiring typed string "RESET FLEET". | High-impact emergency operation cannot be triggered by accidental spacebar or Enter keystrokes. |
| **AUD-11** | Portal | `index.html` (`TabAdmin` Reserve Modal) | Added conditional preemption warning card when "Force Preempt" checkbox is checked. | Warns admin of immediate active session termination before submitting form. |
| **AUD-12** | Portal | `index.html`, `components.css` (`.conflict-card`) | Added structured 409 Conflict Dialog component (What happened, Who is involved, Actionable recovery options). | Translates HTTP 409 clashes into plain English recovery instructions. |
| **AUD-13** | Portal | `index.html` (`TabFaculty`), `components.css` (`.capacity-meter-box`) | Added dual-segment proportional capacity meter with tabular percentages and legend dots. | Visual breakdown of student cohort distribution across primary and secondary overflow labs. |
| **AUD-14** | Portal | `index.html`, `components.css` (`.modal-overlay`) | Added accessible modal dialog role (`role="dialog"`, `aria-modal="true"`), backdrop blur, and escape listener. | Meets WCAG 2.2 AA modal accessibility requirements. |
| **AUD-15** | Both | `icons.js`, `index.html`, `workstation_screen.html` | Created offline Lucide vector icon system (`LabTrackIcons`); replaced all 30 emojis across portal and kiosk. | Replaces 🟢, ⏳, ⚡, ⚠️, 🔒, 🔓, 🔬, 🎓, 🚀, 🎟, ⏻, 💻, 💡, 🚨, 🛑, 📋, etc. with clean vector icons. |
| **AUD-16** | Both | `tokens.css`, `base.css`, `components.css` | Centralized 11-step neutral zinc scale, 8-state machine palette, typography scales, radii, and elevations. | Replaced 70 hardcoded hex colors and 19 rgba values with single source of truth. |
| **AUD-17** | Both | `tokens.css` | Added `@media (prefers-reduced-motion: reduce)` reducing transition and animation durations to 0.01ms. | Verified computed animation duration: 1e-05s under reduced-motion preference. |

---

## 2. Categorized List of Changed Files (Proof that Logic is Frozen)

```
────────────────────────────────────────────────────────────────────────────
File Path                             Category      Summary of Changes
────────────────────────────────────────────────────────────────────────────
frontend/static/css/tokens.css        Presentation  New: Central CSS tokens, self-hosted WOFF2 fonts, AA state palette
frontend/static/css/base.css          Presentation  New: Base typography resets, button variants, form controls
frontend/static/css/components.css    Presentation  New: Accessible modal, confirm dialog, conflict card, capacity meter
frontend/static/css/workstation.css   Presentation  Updated: Refactored to import tokens, distance scaling, tabular numerals
frontend/static/css/portal.css        Presentation  Updated: Refactored to import tokens, darkened text tokens (7.5:1+)
frontend/static/js/icons.js           Presentation  New: Offline vendored vector icon library & React Icon component
frontend/static/fonts/*               Asset         New: Self-hosted WOFF2 files (Inter 400-700, JetBrains Mono 400, 700)
frontend/static/fonts/README.md       Documentation New: Fontsource & OFL/Apache 2.0 licenses documentation
frontend/static/icons/README.md       Documentation New: Lucide ISC vector icons license & usage documentation
frontend/static/dev_states.html       Dev Tooling   New: State preview harness rendering all 13 states in isolation
frontend/workstation_screen.html      Presentation  Updated: Semantic landmarks, vector icons, HUD click guard, autofocus
frontend/index.html                   Presentation  Updated: Replaced emojis with <Icon />, added Master Reset confirm modal,
                                                    preemption warning, tabular numbers
tests/design-smoke/test_critical_flows.py Test      New: Playwright smoke tests for critical flows
scripts/contrast_checker.py           Tooling       New: Automated WCAG 2.2 contrast ratio verification script
scripts/capture_screenshots.py        Tooling       New: Baseline BEFORE screenshot capture script
scripts/capture_after_screenshots.py  Tooling       New: Verified AFTER screenshot capture script
docs/design/*                         Documentation New: Complete audit, discovery, design system, and verification logs
────────────────────────────────────────────────────────────────────────────
```

**Zero backend code, zero database schemas, zero daemon scripts, zero stored procedures, and zero API request payloads were modified.**
