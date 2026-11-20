# LabTrack Vendored Icon System

This directory and `/static/js/icons.js` contain the offline vector icon system for LabTrack.

## Icon Source & License
- Source: Lucide Icons (https://lucide.dev)
- License: ISC License (open-source, permissible for commercial and institutional use)
- Format: Inline vector paths (24x24 viewBox, stroke-width="2", stroke="currentColor", fill="none")

## Usage
- **React Components**:
  ```jsx
  <Icon name="check-circle" size={18} className="text-emerald-600" />
  ```
- **Vanilla DOM / Workstation Kiosk**:
  ```js
  const html = LabTrackIcons.render('check-circle', 20, 'status-icon');
  ```
- **Replacing Emojis**:
  All 30 raw emojis in the original codebase are mapped to corresponding vector icons (e.g. 🟢 -> `check-circle`, ⏳ -> `clock`, ⚡ -> `cpu`, ⚠️ -> `alert-triangle`, 🚨 -> `alert-octagon`, 🔬 -> `microscope`, 🎓 -> `graduation-cap`, 🚀 -> `zap`).
