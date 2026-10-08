-- LabTrack Triggers
-- Target: PostgreSQL 16
-- Enforces automatic timestamp updates, state transition auditing, and license limits

-- 1. Timestamp Updater Function
CREATE OR REPLACE FUNCTION fn_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply timestamp triggers
DROP TRIGGER IF EXISTS trg_pcs_updated_at ON pcs;
CREATE TRIGGER trg_pcs_updated_at
BEFORE UPDATE ON pcs
FOR EACH ROW
EXECUTE FUNCTION fn_update_timestamp();

DROP TRIGGER IF EXISTS trg_reservations_updated_at ON reservations;
CREATE TRIGGER trg_reservations_updated_at
BEFORE UPDATE ON reservations
FOR EACH ROW
EXECUTE FUNCTION fn_update_timestamp();

DROP TRIGGER IF EXISTS trg_licenses_updated_at ON licenses;
CREATE TRIGGER trg_licenses_updated_at
BEFORE UPDATE ON licenses
FOR EACH ROW
EXECUTE FUNCTION fn_update_timestamp();

-- 2. Audit PC State Transitions Trigger
CREATE OR REPLACE FUNCTION fn_audit_pc_state_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.state IS DISTINCT FROM NEW.state THEN
        INSERT INTO audit_logs (event_type, pc_id, details)
        VALUES (
            'PC_STATE_CHANGED',
            NEW.id,
            jsonb_build_object(
                'hostname', NEW.hostname,
                'old_state', OLD.state,
                'new_state', NEW.state
            )
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pcs_state_audit ON pcs;
CREATE TRIGGER trg_pcs_state_audit
AFTER UPDATE OF state ON pcs
FOR EACH ROW
EXECUTE FUNCTION fn_audit_pc_state_change();
