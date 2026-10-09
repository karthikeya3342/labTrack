-- LabTrack Database Schema
-- Target: PostgreSQL 16
-- Description: Core tables, enums, and GiST exclusion constraints for lab resource tracking

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Drop tables in reverse dependency order if recreating
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS telemetry_samples CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS reservations CASCADE;
DROP TABLE IF EXISTS licenses CASCADE;
DROP TABLE IF EXISTS software CASCADE;
DROP TABLE IF EXISTS pcs CASCADE;
DROP TABLE IF EXISTS labs CASCADE;
DROP TABLE IF EXISTS faculty_profiles CASCADE;
DROP TABLE IF EXISTS student_profiles CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS departments CASCADE;

-- 1. Departments Table
CREATE TABLE departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    code VARCHAR(20) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 2. Users Table (Students, Faculty, Lab Admins)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    roll_no VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('student', 'faculty', 'admin')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Student Profiles
CREATE TABLE student_profiles (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    department_id INT REFERENCES departments(id) ON DELETE SET NULL,
    batch_year INT NOT NULL DEFAULT 2026,
    cgpa NUMERIC(4,2) DEFAULT 8.00,
    quota_hours_remaining NUMERIC(6,2) DEFAULT 40.00,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 4. Faculty Profiles
CREATE TABLE faculty_profiles (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    department_id INT REFERENCES departments(id) ON DELETE SET NULL,
    designation VARCHAR(50) DEFAULT 'Assistant Professor',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 5. Labs Table
CREATE TABLE labs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    code VARCHAR(20) UNIQUE NOT NULL,
    department_id INT REFERENCES departments(id) ON DELETE SET NULL,
    capacity INT NOT NULL CHECK (capacity > 0),
    location VARCHAR(100) NOT NULL,
    has_gpu BOOLEAN DEFAULT FALSE,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. Workstation PCs Table
CREATE TABLE pcs (
    id SERIAL PRIMARY KEY,
    hostname VARCHAR(50) UNIQUE NOT NULL,
    lab_id INT REFERENCES labs(id) ON DELETE CASCADE,
    ip_address VARCHAR(45),
    mac_address VARCHAR(20),
    state VARCHAR(20) DEFAULT 'AVAILABLE' CHECK (state IN ('AVAILABLE', 'HELD', 'OCCUPIED', 'MAINTENANCE')),
    specifications JSONB DEFAULT '{"cpu": "Intel Core i7-13700", "ram_gb": 32, "gpu": "None", "os": "Ubuntu 24.04"}'::jsonb,
    last_heartbeat TIMESTAMPTZ,
    maintenance_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 7. Software Table
CREATE TABLE software (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(50) NOT NULL,
    requires_gpu BOOLEAN DEFAULT FALSE,
    total_seats INT NOT NULL DEFAULT 10 CHECK (total_seats > 0),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 8. Software Licenses Semaphore Table
CREATE TABLE licenses (
    id SERIAL PRIMARY KEY,
    software_id INT REFERENCES software(id) ON DELETE CASCADE UNIQUE,
    active_seats INT DEFAULT 0 CHECK (active_seats >= 0),
    max_seats INT NOT NULL CHECK (max_seats > 0),
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_license_seats CHECK (active_seats <= max_seats)
);

-- 9. Reservations Table with GiST Exclusion Constraint for Overlapping Time Ranges
CREATE TABLE reservations (
    id SERIAL PRIMARY KEY,
    student_id INT REFERENCES users(id) ON DELETE CASCADE,
    pc_id INT REFERENCES pcs(id) ON DELETE CASCADE,
    task_type VARCHAR(50) DEFAULT 'Practice' CHECK (task_type IN ('Practice', 'Senior Project', 'Exam', 'Coursework')),
    software_required TEXT[] DEFAULT ARRAY[]::TEXT[],
    time_range TSTZRANGE NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'HELD', 'ACTIVE', 'COMPLETED', 'CANCELLED', 'EXPIRED', 'NO_SHOW')),
    grace_deadline TIMESTAMPTZ,
    priority_score INT DEFAULT 20,
    allocation_basis TEXT,
    deadline TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    -- GiST Exclusion Constraint: prevent multiple active/held reservations on the same PC during overlapping time windows
    CONSTRAINT no_overlapping_pc_reservations
    EXCLUDE USING gist (
        pc_id WITH =,
        time_range WITH &&
    ) WHERE (status IN ('PENDING', 'HELD', 'ACTIVE'))
);

-- 10. Sessions Table (Active and Historical Machine Check-ins)
CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    reservation_id INT REFERENCES reservations(id) ON DELETE SET NULL,
    pc_id INT REFERENCES pcs(id) ON DELETE CASCADE,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    start_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMPTZ,
    cgroup_path VARCHAR(255),
    workspace_path VARCHAR(255),
    status VARCHAR(20) DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CLOSED', 'TERMINATED')),
    close_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 11. Telemetry Samples Table (/proc and cgroup inspection metrics)
CREATE TABLE telemetry_samples (
    id BIGSERIAL PRIMARY KEY,
    session_id INT REFERENCES sessions(id) ON DELETE CASCADE,
    pc_id INT REFERENCES pcs(id) ON DELETE CASCADE,
    cpu_percent NUMERIC(5,2) DEFAULT 0.00,
    memory_rss_bytes BIGINT DEFAULT 0,
    memory_percent NUMERIC(5,2) DEFAULT 0.00,
    page_faults BIGINT DEFAULT 0,
    process_count INT DEFAULT 0,
    load_average NUMERIC(5,2) DEFAULT 0.00,
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 12. Audit Logs Table
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    user_id INT REFERENCES users(id) ON DELETE SET NULL,
    pc_id INT REFERENCES pcs(id) ON DELETE SET NULL,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
