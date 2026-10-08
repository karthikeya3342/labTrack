#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${PROJECT_ROOT}/bin:${PATH}"
export LD_LIBRARY_PATH="${PROJECT_ROOT}/.postgres_dist/usr/lib/x86_64-linux-gnu:${PROJECT_ROOT}/.postgres_dist/usr/lib/postgresql/16/lib:${LD_LIBRARY_PATH}"

PG_DATA="${PROJECT_ROOT}/.pg_data"
PG_SOCKET="${PROJECT_ROOT}/.pg_socket"
PG_PORT=5432
PG_LOG="${PROJECT_ROOT}/postgres.log"

echo "=========================================================="
echo "Initializing LabTrack PostgreSQL 16 Relational Engine..."
echo "=========================================================="

mkdir -p "${PG_SOCKET}"

# 1. Check if an external / system PostgreSQL instance is responding
SYSTEM_PG_READY=false
if pg_isready -h localhost -p ${PG_PORT} >/dev/null 2>&1; then
    echo "Found active PostgreSQL instance on localhost:${PG_PORT}"
    SYSTEM_PG_READY=true
fi

if [ "$SYSTEM_PG_READY" = false ]; then
    # Check if local cluster is initialized
    if [ ! -d "${PG_DATA}" ] || [ ! -f "${PG_DATA}/PG_VERSION" ]; then
        echo "Initializing local PostgreSQL 16 cluster in ${PG_DATA}..."
        initdb -D "${PG_DATA}" -E UTF8 --no-locale -A trust
    fi

    # Check if local postgres is already running
    if ! pg_isready -h "${PG_SOCKET}" -p ${PG_PORT} >/dev/null 2>&1; then
        echo "Starting local PostgreSQL 16 server..."
        pg_ctl -D "${PG_DATA}" -l "${PG_LOG}" -o "-k ${PG_SOCKET} -p ${PG_PORT} -h 127.0.0.1" start
        sleep 2
    fi
fi

# Verify server readiness
MAX_RETRIES=15
COUNTER=0
until pg_isready -h "${PG_SOCKET}" -p ${PG_PORT} >/dev/null 2>&1 || pg_isready -h 127.0.0.1 -p ${PG_PORT} >/dev/null 2>&1 || [ $COUNTER -eq $MAX_RETRIES ]; do
    echo "Waiting for PostgreSQL to be ready ($COUNTER/$MAX_RETRIES)..."
    sleep 1
    COUNTER=$((COUNTER + 1))
done

echo "PostgreSQL 16 is responsive!"

# 2. Create labtrack database if it doesn't exist
PG_TARGET_HOST="${PG_SOCKET}"
if ! psql -h "${PG_TARGET_HOST}" -p ${PG_PORT} -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw labtrack; then
    echo "Creating database 'labtrack'..."
    createdb -h "${PG_TARGET_HOST}" -p ${PG_PORT} labtrack || true
fi

# 3. Apply SQL migrations
echo "Applying database/schema.sql..."
psql -h "${PG_TARGET_HOST}" -p ${PG_PORT} -d labtrack -f "${PROJECT_ROOT}/database/schema.sql"

echo "Applying database/procedures.sql..."
psql -h "${PG_TARGET_HOST}" -p ${PG_PORT} -d labtrack -f "${PROJECT_ROOT}/database/procedures.sql"

echo "Applying database/triggers.sql..."
psql -h "${PG_TARGET_HOST}" -p ${PG_PORT} -d labtrack -f "${PROJECT_ROOT}/database/triggers.sql"

echo "Applying database/indexes.sql..."
psql -h "${PG_TARGET_HOST}" -p ${PG_PORT} -d labtrack -f "${PROJECT_ROOT}/database/indexes.sql"

echo "Applying database/seed_data.sql..."
psql -h "${PG_TARGET_HOST}" -p ${PG_PORT} -d labtrack -f "${PROJECT_ROOT}/database/seed_data.sql"

# 4. Generate .env configuration
CURRENT_USER="$(whoami)"
cat << EOF > "${PROJECT_ROOT}/.env"
# LabTrack Configuration
LABTRACK_PORT=8000
LABTRACK_HOST=0.0.0.0
POSTGRES_DB=labtrack
POSTGRES_USER=${CURRENT_USER}
POSTGRES_PORT=${PG_PORT}
POSTGRES_HOST=${PG_SOCKET}
DATABASE_URL=postgresql://${CURRENT_USER}@127.0.0.1:${PG_PORT}/labtrack?host=${PG_SOCKET}
JWT_SECRET=labtrack_super_secret_jwt_key_2026_x86_production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
CAPTIVE_PORTAL_URL=https://10.10.10.2:8090/httpclient.html
EOF

echo "=========================================================="
echo "Verification:"
PC_COUNT=$(psql -h "${PG_TARGET_HOST}" -p ${PG_PORT} -d labtrack -t -c "SELECT count(*) FROM pcs;" | tr -d ' ')
USER_COUNT=$(psql -h "${PG_TARGET_HOST}" -p ${PG_PORT} -d labtrack -t -c "SELECT count(*) FROM users;" | tr -d ' ')
echo "Total Workstations Seeded: ${PC_COUNT}"
echo "Total Users Seeded: ${USER_COUNT}"
echo "PostgreSQL 16 Setup Complete!"
echo "=========================================================="
