#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

export LABTRACK_SERVER_URL="${LABTRACK_SERVER_URL:-http://127.0.0.1:8000}"
export LABTRACK_HOSTNAME="${LABTRACK_HOSTNAME:-COMP-PC-01}"
export CAPTIVE_PORTAL_URL="${CAPTIVE_PORTAL_URL:-https://10.10.10.2:8090/httpclient.html}"

echo "=========================================================="
echo "Starting LabTrack Workstation Agent Daemon..."
echo "Target Server URL: ${LABTRACK_SERVER_URL}"
echo "Client Hostname:   ${LABTRACK_HOSTNAME}"
echo "Captive Portal:    ${CAPTIVE_PORTAL_URL}"
echo "=========================================================="

exec "${PROJECT_ROOT}/venv/bin/python3" "${PROJECT_ROOT}/agent/labtrack_agent.py"
