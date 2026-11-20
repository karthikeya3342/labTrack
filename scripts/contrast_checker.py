"""
WCAG 2.2 AA Contrast Ratio Checker
Verifies foreground and background token pairings.
Formula:
L = 0.2126 * R + 0.7152 * G + 0.0722 * B
Ratio = (L1 + 0.05) / (L2 + 0.05)
AA Normal: >= 4.5:1
AA Large (>=18pt or >=14pt bold): >= 3.0:1
"""
import re

def parse_color(c_str):
    c_str = c_str.strip()
    if c_str.startswith('#'):
        hex_val = c_str.lstrip('#')
        if len(hex_val) == 3:
            hex_val = ''.join([ch*2 for ch in hex_val])
        if len(hex_val) == 6:
            r = int(hex_val[0:2], 16)
            g = int(hex_val[2:4], 16)
            b = int(hex_val[4:6], 16)
            return (r, g, b)
    elif c_str.startswith('rgb'):
        m = re.findall(r'\d+', c_str)
        if len(m) >= 3:
            return (int(m[0]), int(m[1]), int(m[2]))
    return None

def linearize(val):
    c = val / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def relative_luminance(rgb):
    r, g, b = rgb
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)

def contrast_ratio(c1, c2):
    rgb1 = parse_color(c1)
    rgb2 = parse_color(c2)
    if not rgb1 or not rgb2:
        return None
    l1 = relative_luminance(rgb1)
    l2 = relative_luminance(rgb2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)

def check_pairing(name, fg, bg, min_ratio=4.5):
    ratio = contrast_ratio(fg, bg)
    if ratio is None:
        return f"{name}: Unable to parse ({fg} on {bg})"
    status = "PASS" if ratio >= min_ratio else "FAIL"
    return f"[{status}] {name}: {ratio:.2f}:1 (Req: {min_ratio}:1) -- FG: {fg}, BG: {bg}"

if __name__ == "__main__":
    # Test current kiosk token pairings
    print("=== Current Kiosk Token Pairings ===")
    kiosk_pairs = [
        ("Available Banner Text on BG", "#4ade80", "#052e16", 4.5),
        ("Held Banner Text on BG", "#fbbf24", "#451a03", 4.5),
        ("Occupied Banner Text on BG", "#818cf8", "#1e1b4b", 4.5),
        ("Maintenance Banner Text on BG", "#f87171", "#450a0a", 4.5),
        ("Page Main Text on Card BG", "#f4f4f5", "#18181b", 4.5),
        ("Text Muted on Card BG", "#a1a1aa", "#18181b", 4.5),
        ("Text Light on Card BG", "#71717a", "#18181b", 4.5),
        ("Lab Name Sub on Topbar BG", "#71717a", "#0c0c0e", 4.5),
        ("Footer Text on Page BG", "#52525b", "#09090b", 4.5),
        ("Roll Number Label on Card BG", "#a1a1aa", "#18181b", 4.5),
        ("HUD Telemetry Chip on HUD BG", "#cbd5e1", "#09090b", 4.5),
    ]
    for name, fg, bg, req in kiosk_pairs:
        print(check_pairing(name, fg, bg, req))

    print("\n=== Current Portal Token Pairings ===")
    portal_pairs = [
        ("Portal Main Text on Page BG", "#0f172a", "#f8fafc", 4.5),
        ("Portal Muted Text on Page BG", "#64748b", "#f8fafc", 4.5),
        ("Portal Light Text on Card BG", "#94a3b8", "#ffffff", 4.5),
        ("Avail Badge Text on Avail BG", "#15803d", "#f0fdf4", 4.5),
        ("Held Badge Text on Held BG", "#b45309", "#fffbeb", 4.5),
        ("Occ Badge Text on Occ BG", "#b91c1c", "#fef2f2", 4.5),
        ("Maint Badge Text on Maint BG", "#475569", "#f8fafc", 4.5),
        ("Admin Stat Muted Label on Stat Card", "#64748b", "#ffffff", 4.5),
    ]
    for name, fg, bg, req in portal_pairs:
        print(check_pairing(name, fg, bg, req))
