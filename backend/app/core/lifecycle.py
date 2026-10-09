"""
LabTrack Resource Lifecycle & Self-Healing Sweeper Engine
Handles:
1. Automatic expiration of completed club events (status -> 'COMPLETED').
2. Automatic expiration of completed bulk and individual reservations (status -> 'COMPLETED').
3. Marking missed reservations past grace deadline as 'NO_SHOW'.
4. Self-healing restoration of workstations from HELD / stuck OCCUPIED back to AVAILABLE.
"""

from datetime import datetime, timezone
from typing import Dict, Any
from backend.app.core.database import execute, fetch_all, fetch_val
import logging

logger = logging.getLogger("LabTrackLifecycle")

def parse_row_count(res: Any) -> int:
    if not res:
        return 0
    if isinstance(res, int):
        return res
    if isinstance(res, str):
        parts = res.split()
        if len(parts) >= 2 and parts[-1].isdigit():
            return int(parts[-1])
    return 0

async def reap_expired_allocations() -> Dict[str, int]:
    """
    Executes automated lifecycle sweeps across club events, reservations, and workstations.
    Safe to call concurrently and periodically.
    """
    now = datetime.now(timezone.utc)

    # 0. Promote PENDING reservations to HELD when within 10 minutes of start time
    # This covers Club Events, Faculty Extra Labs, and Advance Student Bookings
    res_promoted = await execute("""
        UPDATE reservations
        SET status = 'HELD', updated_at = CURRENT_TIMESTAMP
        WHERE status = 'PENDING'
          AND lower(time_range) <= (CURRENT_TIMESTAMP + INTERVAL '10 minutes')
          AND upper(time_range) > CURRENT_TIMESTAMP;
    """)

    # Put corresponding PCs in HELD state (if not occupied by active session or in maintenance)
    pcs_promoted_to_held = await execute("""
        UPDATE pcs p
        SET state = 'HELD', updated_at = CURRENT_TIMESTAMP
        WHERE p.state = 'AVAILABLE'
          AND EXISTS (
              SELECT 1 FROM reservations r
              WHERE r.pc_id = p.id
                AND r.status = 'HELD'
                AND lower(r.time_range) <= (CURRENT_TIMESTAMP + INTERVAL '10 minutes')
                AND upper(r.time_range) > CURRENT_TIMESTAMP
          );
    """)

    # 1. Complete expired club events
    events_reaped = await execute("""
        UPDATE club_events
        SET status = 'COMPLETED'
        WHERE status = 'APPROVED'
          AND upper(time_range) <= CURRENT_TIMESTAMP;
    """)

    # 1b. Complete all reservations linked to completed/expired club events or batches
    res_completed = await execute("""
        UPDATE reservations
        SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('PENDING', 'HELD', 'ACTIVE')
          AND (
              (club_event_id IS NOT NULL AND EXISTS (
                  SELECT 1 FROM club_events ce WHERE ce.id = reservations.club_event_id AND (ce.status = 'COMPLETED' OR upper(ce.time_range) <= CURRENT_TIMESTAMP)
              ))
              OR (upper(time_range) <= CURRENT_TIMESTAMP)
          );
    """)

    # 1c. Close all active student sessions whose event or reservation has ended
    sessions_closed = await execute("""
        UPDATE sessions s
        SET status = 'CLOSED', end_time = CURRENT_TIMESTAMP, close_reason = 'Scheduled event/reservation completed'
        WHERE s.status = 'ACTIVE'
          AND (
              EXISTS (
                  SELECT 1 FROM club_events ce
                  WHERE ce.id = s.club_event_id
                    AND (ce.status = 'COMPLETED' OR upper(ce.time_range) <= CURRENT_TIMESTAMP)
              )
              OR EXISTS (
                  SELECT 1 FROM reservations r
                  WHERE r.id = s.reservation_id
                    AND (r.status = 'COMPLETED' OR upper(r.time_range) <= CURRENT_TIMESTAMP)
              )
          );
    """)

    # 2. Mark individual student HELD reservations past grace deadline as NO_SHOW
    no_shows = await execute("""
        UPDATE reservations
        SET status = 'NO_SHOW', updated_at = CURRENT_TIMESTAMP
        WHERE status = 'HELD'
          AND club_event_id IS NULL
          AND batch_name IS NULL
          AND grace_deadline IS NOT NULL
          AND grace_deadline <= CURRENT_TIMESTAMP;
    """)

    # 4. Restore workstations in HELD state back to AVAILABLE if neither active club event nor valid HELD reservation exists
    pcs_freed_from_held = await execute("""
        UPDATE pcs p
        SET state = 'AVAILABLE', updated_at = CURRENT_TIMESTAMP
        WHERE p.state = 'HELD'
          AND NOT EXISTS (
              SELECT 1 FROM club_events ce
              WHERE (ce.lab_id = p.lab_id OR ce.secondary_lab_id = p.lab_id)
                AND ce.status = 'APPROVED'
                AND upper(ce.time_range) > CURRENT_TIMESTAMP
                AND lower(ce.time_range) <= (CURRENT_TIMESTAMP + INTERVAL '10 minutes')
          )
          AND NOT EXISTS (
              SELECT 1 FROM reservations r
              WHERE r.pc_id = p.id
                AND r.status = 'HELD'
                AND (r.grace_deadline IS NULL OR r.grace_deadline > CURRENT_TIMESTAMP)
                AND lower(r.time_range) <= (CURRENT_TIMESTAMP + INTERVAL '10 minutes')
                AND upper(r.time_range) > CURRENT_TIMESTAMP
          );
    """)

    # 5. Restore workstations in OCCUPIED state back to AVAILABLE if no ACTIVE session exists
    pcs_freed_from_stuck_occ = await execute("""
        UPDATE pcs p
        SET state = 'AVAILABLE', updated_at = CURRENT_TIMESTAMP
        WHERE p.state = 'OCCUPIED'
          AND NOT EXISTS (
              SELECT 1 FROM sessions s
              WHERE s.pc_id = p.id AND s.status = 'ACTIVE'
          );
    """)

    c_events = parse_row_count(events_reaped)
    c_res = parse_row_count(res_completed)
    c_no_shows = parse_row_count(no_shows)
    c_held = parse_row_count(pcs_freed_from_held)
    c_occ = parse_row_count(pcs_freed_from_stuck_occ)

    total_changes = c_events + c_res + c_no_shows + c_held + c_occ

    if total_changes > 0:
        logger.info(
            f"🧹 [Lifecycle Reaper] Sweep applied: {c_events} events completed, "
            f"{c_res} reservations completed, {c_no_shows} no-shows, "
            f"{c_held} PCs restored from HELD, {c_occ} PCs restored from stuck OCCUPIED."
        )

    return {
        "events_completed": c_events,
        "reservations_completed": c_res,
        "no_shows": c_no_shows,
        "pcs_freed_from_held": c_held,
        "pcs_freed_from_occupied": c_occ
    }
