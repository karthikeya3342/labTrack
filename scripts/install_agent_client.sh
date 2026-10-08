#!/usr/bin/env bash
# LabTrack Client Workstation Daemon Installer
# Usage:
#   sudo ./scripts/install_agent_client.sh <HOSTNAME> <SERVER_URL>
# Example:
#   sudo ./scripts/install_agent_client.sh COMP-PC-01 http://172.16.72.243:8000

set -e

CLIENT_HOST="${1:-COMP-PC-01}"
SERVER_URL="${2:-http://172.16.72.243:8000}"
CAPTIVE_PORTAL="${3:-https://10.10.10.2:8090/httpclient.html}"

echo "=========================================================="
echo "Installing LabTrack Workstation Agent Daemon"
echo "Target Hostname:    ${CLIENT_HOST}"
echo "Server Control URL: ${SERVER_URL}"
echo "Captive Portal URL: ${CAPTIVE_PORTAL}"
echo "=========================================================="

# 1. Verify Connectivity to Lab Server
echo "Testing LAN connectivity to Lab Server at ${SERVER_URL}/health ..."
if ! curl -s --connect-timeout 4 "${SERVER_URL}/health" >/dev/null; then
    echo "ERROR: Cannot reach Lab Server at ${SERVER_URL}."
    echo "Please verify that the server is running and both PCs are on the same subnet."
    exit 1
fi
echo "Connection to Lab Server verified!"

# 2. Install Python Dependencies
echo "Checking Python 3 environment..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "Installing python3..."
    apt-get update && apt-get install -y python3 python3-pip python3-psutil python3-requests
fi

# Ensure psutil and requests are installed
python3 -c "import psutil, requests" 2>/dev/null || {
    echo "Installing required python packages (psutil, requests)..."
    pip3 install psutil requests --break-system-packages 2>/dev/null || apt-get install -y python3-psutil python3-requests
}

# 3. Create Installation Directory
INSTALL_DIR="/opt/labtrack"
mkdir -p "${INSTALL_DIR}"
mkdir -p /sys/fs/cgroup/labtrack 2>/dev/null || true
mkdir -p /tmp/labtrack 2>/dev/null || true

# 4. Fetch or Copy Agent Script
if [ -f "$(dirname "${BASH_SOURCE[0]}")/../agent/labtrack_agent.py" ]; then
    cp "$(dirname "${BASH_SOURCE[0]}")/../agent/labtrack_agent.py" "${INSTALL_DIR}/labtrack_agent.py"
else
    echo "Downloading labtrack_agent.py from Lab Server..."
    curl -s "${SERVER_URL}/agent/labtrack_agent.py" -o "${INSTALL_DIR}/labtrack_agent.py"
fi
chmod +x "${INSTALL_DIR}/labtrack_agent.py"

# 5. Configure and Install Systemd Service
SERVICE_FILE="/etc/systemd/system/labtrack-agent.service"
echo "Creating systemd unit at ${SERVICE_FILE}..."

cat << EOF > "${SERVICE_FILE}"
[Unit]
Description=LabTrack Workstation Machine Plane Agent Daemon
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${INSTALL_DIR}
Environment="LABTRACK_SERVER_URL=${SERVER_URL}"
Environment="LABTRACK_HOSTNAME=${CLIENT_HOST}"
Environment="CAPTIVE_PORTAL_URL=${CAPTIVE_PORTAL}"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/labtrack_agent.py
Restart=always
RestartSec=3s
KillMode=mixed
TimeoutStopSec=5s

[Install]
WantedBy=multi-user.target
EOF

# 6. Enable and Start Daemon
echo "Reloading systemd daemon and enabling service..."
systemctl daemon-reload
systemctl enable labtrack-agent.service
systemctl restart labtrack-agent.service

# 7. Configure Physical PC Boot Lock Screen Greeter (XDG Desktop Autostart)
mkdir -p /etc/xdg/autostart
AUTOSTART_FILE="/etc/xdg/autostart/labtrack-kiosk.desktop"
echo "Configuring Fullscreen Boot Kiosk Greeter at ${AUTOSTART_FILE}..."

# Detect browser binary
BROWSER_BIN="google-chrome"
if command -v chromium-browser >/dev/null 2>&1; then
    BROWSER_BIN="chromium-browser"
elif command -v chromium >/dev/null 2>&1; then
    BROWSER_BIN="chromium"
elif command -v google-chrome >/dev/null 2>&1; then
    BROWSER_BIN="google-chrome"
fi

cat << EOF > "${AUTOSTART_FILE}"
[Desktop Entry]
Type=Application
Name=LabTrack Workstation Kiosk Greeter
Comment=Fullscreen Physical PC Lock Screen on Boot
Exec=${BROWSER_BIN} --kiosk --no-first-run --no-default-browser-check --disable-translate --disable-pinch --overscroll-history-navigation=0 "${SERVER_URL}/workstation/${CLIENT_HOST}"
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "=========================================================="
echo "LabTrack Agent daemon and Boot Kiosk Greeter installed!"
echo "1. Systemd Service: ACTIVE & ENABLED on boot"
echo "2. Lock Screen Greeter: AUTO-LAUNCHES on system turn on"
systemctl status labtrack-agent.service --no-pager
echo "=========================================================="
