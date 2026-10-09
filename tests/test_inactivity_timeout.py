import pytest
import os
import time
from unittest.mock import patch, MagicMock
from agent.labtrack_agent import WorkstationAgent, IDLE_TIMEOUT_SECONDS, IDLE_WARN_SECONDS

def test_inactivity_detection_runs_cleanly():
    """Verify get_inactivity_seconds executes without exceptions."""
    agent = WorkstationAgent()
    idle_sec = agent.get_inactivity_seconds()
    assert isinstance(idle_sec, (int, float))
    assert idle_sec >= 0.0

def test_inactivity_timeout_triggers_auto_close_and_relock():
    """
    Verify that when idle timeout (30 min) is exceeded:
    1. Agent notifies server with inactivity reason
    2. Wipes sandbox
    3. Relocks workstation into kiosk
    4. Resets last_known_state to AVAILABLE
    """
    agent = WorkstationAgent()
    agent.active_session_id = 999
    agent.active_student_roll = "124cs0021"
    agent.last_known_state = "OCCUPIED"

    # Mock inactivity to exceed 30 minutes (e.g. 1850 seconds)
    with patch.object(agent, "get_inactivity_seconds", return_value=1850.0):
        with patch.object(agent, "collect_proc_telemetry", return_value={"cpu_percent": 1.5}):
            with patch("requests.post") as mock_post:
                mock_post.return_value.ok = True
                with patch.object(agent, "lock_workstation_gui") as mock_lock:
                    with patch.object(agent, "wipe_workspace_sandbox") as mock_wipe:
                        with patch("subprocess.run") as mock_subproc:
                            agent.check_inactivity_and_enforce_timeout()

                            # 1. Verify close request sent with inactivity reason
                            close_calls = [c for c in mock_post.call_args_list if "/api/agent/close" in str(c)]
                            assert len(close_calls) > 0, "Expected /api/agent/close to be called"
                            call_kwargs = close_calls[0][1]
                            assert "Session auto-closed due to 30 min user inactivity" in call_kwargs["json"]["reason"]
                            assert call_kwargs["json"]["session_id"] == 999

                            # 2. Verify workspace wiped and screen locked
                            mock_wipe.assert_called()
                            mock_lock.assert_called()

                            # 3. Verify notification was dispatched via notify-send
                            notify_calls = [c for c in mock_subproc.call_args_list if "notify-send" in str(c)]
                            assert len(notify_calls) > 0, "Expected notify-send to be invoked"

                        # 3. Verify state reset to AVAILABLE
                        assert agent.active_session_id is None
                        assert agent.last_known_state == "AVAILABLE"
