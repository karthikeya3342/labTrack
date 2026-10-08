-- LabTrack Stored Procedures
-- Target: PostgreSQL 16
-- Procedures: fn_admit_reservation, fn_checkin_session, fn_close_session

-- 1. fn_admit_reservation: Books an advance slot and sets PC state to HELD if slot is active or approaching
CREATE OR REPLACE FUNCTION fn_admit_reservation(
    p_student_id INT,
    p_pc_id INT,
    p_start TIMESTAMPTZ,
    p_end TIMESTAMPTZ,
    p_task_type TEXT DEFAULT 'Practice',
    p_software TEXT[] DEFAULT ARRAY[]::TEXT[]
) RETURNS INT AS $$
DECLARE
    v_res_id INT;
    v_grace TIMESTAMPTZ;
    v_current_state VARCHAR(20);
    v_now TIMESTAMPTZ := CURRENT_TIMESTAMP;
    v_time_range TSTZRANGE;
BEGIN
    IF p_start >= p_end THEN
        RAISE EXCEPTION 'Invalid reservation window: start time must precede end time';
    END IF;

    -- Verify student role
    PERFORM 1 FROM users WHERE id = p_student_id AND role = 'student';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'User % is not a registered student', p_student_id;
    END IF;

    -- Verify PC exists and is not in maintenance
    SELECT state INTO v_current_state FROM pcs WHERE id = p_pc_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PC % does not exist', p_pc_id;
    END IF;
    IF v_current_state = 'MAINTENANCE' THEN
        RAISE EXCEPTION 'PC % is currently in maintenance', p_pc_id;
    END IF;

    v_grace := p_start + INTERVAL '15 minutes';
    v_time_range := tstzrange(p_start, p_end, '[)');

    -- Insert reservation (GiST constraint automatically prevents overlaps)
    INSERT INTO reservations (
        student_id, pc_id, task_type, software_required, time_range, status, grace_deadline
    ) VALUES (
        p_student_id, p_pc_id, p_task_type, p_software, v_time_range,
        CASE
            WHEN v_now >= (p_start - INTERVAL '10 minutes') AND v_now <= v_grace THEN 'HELD'
            ELSE 'PENDING'
        END,
        v_grace
    ) RETURNING id INTO v_res_id;

    -- If the reservation starts now or very soon, flip PC state to HELD
    IF v_now >= (p_start - INTERVAL '10 minutes') AND v_now <= v_grace THEN
        UPDATE pcs SET state = 'HELD', updated_at = v_now WHERE id = p_pc_id;
    END IF;

    INSERT INTO audit_logs (event_type, user_id, pc_id, details)
    VALUES ('RESERVATION_CREATED', p_student_id, p_pc_id, jsonb_build_object('reservation_id', v_res_id, 'task_type', p_task_type));

    RETURN v_res_id;
END;
$$ LANGUAGE plpgsql;

-- 2. fn_checkin_session: Authenticates student at workstation, strictly enforcing HELD ownership or walk-in backfilling
CREATE OR REPLACE FUNCTION fn_checkin_session(
    p_hostname TEXT,
    p_roll_no TEXT,
    p_cgroup_path TEXT DEFAULT NULL,
    p_workspace_path TEXT DEFAULT NULL
) RETURNS TABLE (
    out_session_id INT,
    out_reservation_id INT,
    out_pc_id INT,
    out_student_id INT,
    out_student_name TEXT,
    out_status TEXT,
    out_message TEXT
) AS $$
DECLARE
    v_user_id INT;
    v_user_name VARCHAR(100);
    v_user_role VARCHAR(20);
    v_pc_id INT;
    v_pc_state VARCHAR(20);
    v_res_id INT := NULL;
    v_res_student_id INT := NULL;
    v_res_student_name VARCHAR(100) := NULL;
    v_session_id INT;
    v_sw_item TEXT;
    v_next_res_start TIMESTAMPTZ;
    v_walkin_end TIMESTAMPTZ;
    v_now TIMESTAMPTZ := CURRENT_TIMESTAMP;
    v_sw_array TEXT[];
BEGIN
    -- 1. Identify User
    SELECT id, name, role INTO v_user_id, v_user_name, v_user_role
    FROM users WHERE (roll_no = p_roll_no OR email = p_roll_no) AND is_active = TRUE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Student roll number % not recognized or inactive', p_roll_no;
    END IF;

    -- 2. Identify PC
    SELECT id, state INTO v_pc_id, v_pc_state
    FROM pcs WHERE hostname = p_hostname;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workstation hostname % not found', p_hostname;
    END IF;

    IF v_pc_state = 'MAINTENANCE' THEN
        RAISE EXCEPTION 'Workstation % is under maintenance', p_hostname;
    END IF;
    IF v_pc_state = 'OCCUPIED' THEN
        RAISE EXCEPTION 'Workstation % is already occupied by an active session', p_hostname;
    END IF;

    -- 3. PC state evaluation
    IF v_pc_state = 'HELD' THEN
        -- Find the active/held reservation for this PC
        SELECT r.id, r.student_id, u.name, r.software_required
        INTO v_res_id, v_res_student_id, v_res_student_name, v_sw_array
        FROM reservations r
        JOIN users u ON u.id = r.student_id
        WHERE r.pc_id = v_pc_id
          AND r.status = 'HELD'
          AND v_now < r.grace_deadline
        ORDER BY r.created_at DESC
        LIMIT 1;

        IF v_res_id IS NOT NULL THEN
            IF v_res_student_id <> v_user_id THEN
                -- STRICT ACCESS ENFORCEMENT
                RAISE EXCEPTION 'Access Denied: Workstation reserved for %. Please use an available machine.', v_res_student_name;
            ELSE
                -- Reserved student matched
                UPDATE reservations SET status = 'ACTIVE', updated_at = v_now WHERE id = v_res_id;
            END IF;
        ELSE
            -- Grace deadline passed or no reservation found: treat as expired
            UPDATE reservations SET status = 'NO_SHOW', updated_at = v_now
            WHERE pc_id = v_pc_id AND status = 'HELD';
            v_pc_state := 'AVAILABLE';
        END IF;
    END IF;

    -- 4. If Available (or fell back to available): perform walk-in checkin with backfilling
    IF v_pc_state = 'AVAILABLE' THEN
        -- Look ahead for the earliest upcoming reservation on this PC
        SELECT lower(time_range) INTO v_next_res_start
        FROM reservations
        WHERE pc_id = v_pc_id
          AND status IN ('PENDING', 'HELD')
          AND lower(time_range) > v_now
        ORDER BY lower(time_range) ASC
        LIMIT 1;

        IF v_next_res_start IS NOT NULL THEN
            -- Backfill up to 10 minutes prior to next booking, cap at 2 hours
            v_walkin_end := LEAST(v_now + INTERVAL '2 hours', v_next_res_start - INTERVAL '5 minutes');
        ELSE
            v_walkin_end := v_now + INTERVAL '2 hours';
        END IF;

        IF v_walkin_end <= v_now + INTERVAL '10 minutes' THEN
            RAISE EXCEPTION 'Workstation % has an upcoming reservation starting shortly at %', p_hostname, v_next_res_start;
        END IF;

        -- Create walk-in reservation
        INSERT INTO reservations (
            student_id, pc_id, task_type, time_range, status, grace_deadline
        ) VALUES (
            v_user_id, v_pc_id, 'Practice', tstzrange(v_now, v_walkin_end, '[)'), 'ACTIVE', v_now + INTERVAL '15 minutes'
        ) RETURNING id INTO v_res_id;
    END IF;

    -- 5. Create Session
    INSERT INTO sessions (
        reservation_id, pc_id, user_id, start_time, cgroup_path, workspace_path, status
    ) VALUES (
        v_res_id, v_pc_id, v_user_id, v_now, p_cgroup_path, p_workspace_path, 'ACTIVE'
    ) RETURNING id INTO v_session_id;

    -- 6. Update Workstation state
    UPDATE pcs SET state = 'OCCUPIED', updated_at = v_now WHERE id = v_pc_id;

    -- 7. Acquire Software Licenses if needed
    IF v_sw_array IS NOT NULL THEN
        FOREACH v_sw_item IN ARRAY v_sw_array LOOP
            UPDATE licenses l
            SET active_seats = active_seats + 1, updated_at = v_now
            FROM software s
            WHERE l.software_id = s.id AND s.name = v_sw_item AND l.active_seats < l.max_seats;
        END LOOP;
    END IF;

    -- 8. Audit Log
    INSERT INTO audit_logs (event_type, user_id, pc_id, details)
    VALUES ('SESSION_START', v_user_id, v_pc_id, jsonb_build_object('session_id', v_session_id, 'reservation_id', v_res_id));

    out_session_id := v_session_id;
    out_reservation_id := v_res_id;
    out_pc_id := v_pc_id;
    out_student_id := v_user_id;
    out_student_name := v_user_name;
    out_status := 'UNLOCKED';
    out_message := 'Session check-in successful';
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- 3. fn_close_session: Closes an active session, frees PC to AVAILABLE, decrements licenses, logs audit
CREATE OR REPLACE FUNCTION fn_close_session(
    p_session_id INT,
    p_reason TEXT DEFAULT 'Student Logout'
) RETURNS BOOLEAN AS $$
DECLARE
    v_pc_id INT;
    v_user_id INT;
    v_res_id INT;
    v_sw_array TEXT[];
    v_sw_item TEXT;
    v_now TIMESTAMPTZ := CURRENT_TIMESTAMP;
BEGIN
    SELECT pc_id, user_id, reservation_id
    INTO v_pc_id, v_user_id, v_res_id
    FROM sessions
    WHERE id = p_session_id AND status = 'ACTIVE';

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Close session
    UPDATE sessions
    SET status = 'CLOSED', end_time = v_now, close_reason = p_reason
    WHERE id = p_session_id;

    -- Update reservation if linked
    IF v_res_id IS NOT NULL THEN
        SELECT software_required INTO v_sw_array FROM reservations WHERE id = v_res_id;
        UPDATE reservations SET status = 'COMPLETED', updated_at = v_now WHERE id = v_res_id;
    END IF;

    -- Restore Workstation state
    UPDATE pcs SET state = 'AVAILABLE', updated_at = v_now WHERE id = v_pc_id;

    -- Release Software Licenses
    IF v_sw_array IS NOT NULL THEN
        FOREACH v_sw_item IN ARRAY v_sw_array LOOP
            UPDATE licenses l
            SET active_seats = GREATEST(0, active_seats - 1), updated_at = v_now
            FROM software s
            WHERE l.software_id = s.id AND s.name = v_sw_item;
        END LOOP;
    END IF;

    -- Audit log
    INSERT INTO audit_logs (event_type, user_id, pc_id, details)
    VALUES ('SESSION_CLOSE', v_user_id, v_pc_id, jsonb_build_object('session_id', p_session_id, 'reason', p_reason));

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;
