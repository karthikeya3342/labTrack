#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${PROJECT_ROOT}/bin:${PATH}"
export LD_LIBRARY_PATH="${PROJECT_ROOT}/.postgres_dist/usr/lib/x86_64-linux-gnu:${PROJECT_ROOT}/.postgres_dist/usr/lib/postgresql/16/lib:${LD_LIBRARY_PATH}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

PG_DATA="${PROJECT_ROOT}/.pg_data"
PG_SOCKET="${PROJECT_ROOT}/.pg_socket"
PG_PORT=5432
PG_LOG="${PROJECT_ROOT}/postgres.log"

echo "=========================================================="
echo "Starting LabTrack Control Plane Server..."
echo "=========================================================="

# Ensure PostgreSQL 16 is running
if ! pg_isready -h "${PG_SOCKET}" -p ${PG_PORT} >/dev/null 2>&1 && ! pg_isready -h 127.0.0.1 -p ${PG_PORT} >/dev/null 2>&1; then
    echo "PostgreSQL is not running. Initializing / starting..."
    if [ ! -d "${PG_DATA}" ] || [ ! -f "${PG_DATA}/PG_VERSION" ]; then
        "${PROJECT_ROOT}/scripts/setup_postgres.sh"
    else
        mkdir -p "${PG_SOCKET}"
        pg_ctl -D "${PG_DATA}" -l "${PG_LOG}" -o "-k ${PG_SOCKET} -p ${PG_PORT} -h 127.0.0.1" start
        sleep 2
    fi
fi

# Load .env if present
if [ -f "${PROJECT_ROOT}/.env" ]; then
    export $(grep -v '^#' "${PROJECT_ROOT}/.env" | xargs)
fi

PORT="${LABTRACK_PORT:-8000}"
HOST="${LABTRACK_HOST:-0.0.0.0}"

echo "Starting FastAPI Backend on http://${HOST}:${PORT} ..."
exec "${PROJECT_ROOT}/venv/bin/uvicorn" backend.app.main:app --host "${HOST}" --port "${PORT}"
