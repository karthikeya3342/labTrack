# LabTrack Self-Hosted Fonts

This directory contains offline-vendored WOFF2 web fonts for the LabTrack platform.

## Vendored Fonts
1. **Inter** (Regular 400, Medium 500, Semi-Bold 600, Bold 700)
   - Source: Fontsource / Inter Software
   - License: SIL Open Font License 1.1 (OFL)
   - Usage: Primary user interface typography across Web Portal and Kiosk screens.
2. **JetBrains Mono** (Regular 400, Bold 700)
   - Source: Fontsource / JetBrains
   - License: Apache 2.0
   - Usage: Tabular numbers (`font-variant-numeric: tabular-nums`), countdown timers, hardware telemetry percentages, hostnames, and roll numbers.

## Offline Guarantee
All fonts are strictly hosted on the local server at `/static/fonts/*.woff2`. The frontend makes ZERO external requests to Google Fonts or CDNs at runtime.

## How to Update
To update font subsets on a machine with internet access:
```bash
python3 -c "
import urllib.request
urls = [
    ('inter-latin-400-normal.woff2', 'https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-400-normal.woff2'),
    ('inter-latin-500-normal.woff2', 'https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-500-normal.woff2'),
    ('inter-latin-600-normal.woff2', 'https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-600-normal.woff2'),
    ('inter-latin-700-normal.woff2', 'https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-700-normal.woff2'),
    ('jetbrains-mono-latin-400-normal.woff2', 'https://cdn.jsdelivr.net/fontsource/fonts/jetbrains-mono@latest/latin-400-normal.woff2'),
    ('jetbrains-mono-latin-700-normal.woff2', 'https://cdn.jsdelivr.net/fontsource/fonts/jetbrains-mono@latest/latin-700-normal.woff2')
]
for fname, url in urls:
    urllib.request.urlretrieve(url, f'frontend/static/fonts/{fname}')
"
```
