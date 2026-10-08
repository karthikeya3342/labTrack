-- LabTrack Database Indexes
-- Target: PostgreSQL 16
-- Optimizes workstation lookups, reservation searches, and telemetry streaming

CREATE INDEX IF NOT EXISTS idx_users_roll_no ON users(roll_no);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

CREATE INDEX IF NOT EXISTS idx_pcs_hostname ON pcs(hostname);
CREATE INDEX IF NOT EXISTS idx_pcs_lab_id ON pcs(lab_id);
CREATE INDEX IF NOT EXISTS idx_pcs_state ON pcs(state);

CREATE INDEX IF NOT EXISTS idx_reservations_student_id ON reservations(student_id);
CREATE INDEX IF NOT EXISTS idx_reservations_pc_id ON reservations(pc_id);
CREATE INDEX IF NOT EXISTS idx_reservations_status ON reservations(status);
CREATE INDEX IF NOT EXISTS idx_reservations_time_range ON reservations USING gist(time_range);

CREATE INDEX IF NOT EXISTS idx_sessions_pc_id ON sessions(pc_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE INDEX IF NOT EXISTS idx_telemetry_session_time ON telemetry_samples(session_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_pc_time ON telemetry_samples(pc_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_event_time ON audit_logs(event_type, created_at DESC);
