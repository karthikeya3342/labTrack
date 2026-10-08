-- LabTrack Initial Seed Data
-- Workstations:
-- Lab 1 (Computing Lab): COMP-PC-01 to COMP-PC-20
-- Lab 2 (Software Eng): SE-PC-01 to SE-PC-15
-- Lab 3 (AI Lab): AI-PC-01 to AI-PC-10

-- 1. Departments
INSERT INTO departments (id, name, code) VALUES
(1, 'Computer Science & Engineering', 'CSE'),
(2, 'Software Engineering', 'SE'),
(3, 'Artificial Intelligence & Data Science', 'AI')
ON CONFLICT (code) DO NOTHING;

-- 2. Users (Admin, Faculty, Students)
-- Passwords:
-- admin: admin123
-- faculty01: faculty123
-- STU001-STU005: stu123
INSERT INTO users (id, roll_no, name, email, password_hash, role) VALUES
(1, 'admin', 'System Administrator', 'admin@labtrack.local', '$2b$12$ug1bn6FZDzEf4GraaoL3fuGKUVS4hmfWnvaRACUcZKsGhhKaczMOi', 'admin'),
(2, 'faculty01', 'Dr. Alan Turing', 'alan.turing@labtrack.local', '$2b$12$lG8mjUzFYZwuDrZoF2qAg.2cfOMvuL6TLO.3dVU4qOhNEO0eT6Qv6', 'faculty'),
(3, 'STU001', 'Alice Johnson', 'alice.johnson@labtrack.local', '$2b$12$3eeba334..0/5cx45tfAzORuMaJpXTYITeMPqLgMPqB/lpHUmrzHK', 'student'),
(4, 'STU002', 'Bob Smith', 'bob.smith@labtrack.local', '$2b$12$3eeba334..0/5cx45tfAzORuMaJpXTYITeMPqLgMPqB/lpHUmrzHK', 'student'),
(5, 'STU003', 'Charlie Brown', 'charlie.brown@labtrack.local', '$2b$12$3eeba334..0/5cx45tfAzORuMaJpXTYITeMPqLgMPqB/lpHUmrzHK', 'student'),
(6, 'STU004', 'Diana Prince', 'diana.prince@labtrack.local', '$2b$12$3eeba334..0/5cx45tfAzORuMaJpXTYITeMPqLgMPqB/lpHUmrzHK', 'student'),
(7, 'STU005', 'Ethan Hunt', 'ethan.hunt@labtrack.local', '$2b$12$3eeba334..0/5cx45tfAzORuMaJpXTYITeMPqLgMPqB/lpHUmrzHK', 'student')
ON CONFLICT (roll_no) DO NOTHING;

-- Reset sequence for users
SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));

-- 3. Profiles
INSERT INTO faculty_profiles (user_id, department_id, designation) VALUES
(2, 1, 'Professor & Head')
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO student_profiles (user_id, department_id, batch_year, cgpa, quota_hours_remaining) VALUES
(3, 1, 2026, 8.85, 40.0),
(4, 2, 2026, 8.42, 38.5),
(5, 3, 2027, 9.10, 42.0),
(6, 1, 2026, 7.95, 35.0),
(7, 3, 2025, 8.60, 45.0)
ON CONFLICT (user_id) DO NOTHING;

-- 4. Labs
INSERT INTO labs (id, name, code, department_id, capacity, location, has_gpu, description) VALUES
(1, 'Computing Lab', 'LAB-101', 1, 20, 'Block A, 1st Floor, Room 101', FALSE, 'General computing and programming workstations'),
(2, 'Software Engineering Lab', 'LAB-202', 2, 15, 'Block B, 2nd Floor, Room 202', FALSE, 'Full-stack software engineering and modeling lab'),
(3, 'AI & High Performance Lab', 'LAB-303', 3, 10, 'Block C, 3rd Floor, Room 303', TRUE, 'High-end workstations equipped with NVIDIA RTX 4090 GPUs')
ON CONFLICT (code) DO NOTHING;

SELECT setval('labs_id_seq', (SELECT MAX(id) FROM labs));

-- 5. PCs: Lab 1 (COMP-PC-01 to COMP-PC-20)
DO $$
DECLARE
    i INT;
    v_host TEXT;
BEGIN
    FOR i IN 1..20 LOOP
        v_host := 'COMP-PC-' || lpad(i::text, 2, '0');
        INSERT INTO pcs (hostname, lab_id, ip_address, state, specifications)
        VALUES (
            v_host,
            1,
            '192.168.10.' || (10 + i)::text,
            'AVAILABLE',
            jsonb_build_object(
                'cpu', 'Intel Core i7-13700 (16 Cores)',
                'ram_gb', 32,
                'gpu', 'Intel UHD Graphics 770',
                'os', 'Ubuntu 24.04 LTS'
            )
        ) ON CONFLICT (hostname) DO NOTHING;
    END LOOP;
END $$;

-- PCs: Lab 2 (SE-PC-01 to SE-PC-15)
DO $$
DECLARE
    i INT;
    v_host TEXT;
BEGIN
    FOR i IN 1..15 LOOP
        v_host := 'SE-PC-' || lpad(i::text, 2, '0');
        INSERT INTO pcs (hostname, lab_id, ip_address, state, specifications)
        VALUES (
            v_host,
            2,
            '192.168.20.' || (10 + i)::text,
            'AVAILABLE',
            jsonb_build_object(
                'cpu', 'Intel Core i7-14700 (20 Cores)',
                'ram_gb', 32,
                'gpu', 'NVIDIA T1000 8GB',
                'os', 'Ubuntu 24.04 LTS'
            )
        ) ON CONFLICT (hostname) DO NOTHING;
    END LOOP;
END $$;

-- PCs: Lab 3 (AI-PC-01 to AI-PC-10)
DO $$
DECLARE
    i INT;
    v_host TEXT;
BEGIN
    FOR i IN 1..10 LOOP
        v_host := 'AI-PC-' || lpad(i::text, 2, '0');
        INSERT INTO pcs (hostname, lab_id, ip_address, state, specifications)
        VALUES (
            v_host,
            3,
            '192.168.30.' || (10 + i)::text,
            'AVAILABLE',
            jsonb_build_object(
                'cpu', 'AMD Ryzen 9 7950X (16 Cores / 32 Threads)',
                'ram_gb', 64,
                'gpu', 'NVIDIA GeForce RTX 4090 24GB VRAM',
                'os', 'Ubuntu 24.04 LTS'
            )
        ) ON CONFLICT (hostname) DO NOTHING;
    END LOOP;
END $$;

-- 6. Software Applications
INSERT INTO software (id, name, category, requires_gpu, total_seats, description) VALUES
(1, 'MATLAB', 'Simulation & Numerical Computing', FALSE, 10, 'MATLAB & Simulink R2024a Enterprise Edition'),
(2, 'Vivado', 'FPGA & Hardware Design', FALSE, 5, 'Xilinx Vivado Design Suite HLx'),
(3, 'AutoCAD', 'Computer-Aided Design', FALSE, 10, 'Autodesk AutoCAD Educational Multi-User'),
(4, 'PyTorch GPU', 'Deep Learning & AI', TRUE, 10, 'PyTorch CUDA 12.2 Accelerated Environment')
ON CONFLICT (name) DO NOTHING;

SELECT setval('software_id_seq', (SELECT MAX(id) FROM software));

-- 7. Software Licenses
INSERT INTO licenses (software_id, active_seats, max_seats) VALUES
(1, 0, 10),
(2, 0, 5),
(3, 0, 10),
(4, 0, 10)
ON CONFLICT (software_id) DO NOTHING;
