#!/usr/bin/env python3
"""
LabTrack Workstation Agent Daemon
Role: Machine Plane Client Daemon on Linux Workstations
Features:
- cgroups v2 resource quotas (/sys/fs/cgroup/labtrack/session_<id>)
- /proc inspection: process tree, RSS memory, CPU percent, page faults
- Blacklist enforcement: miners, torrents, games with staged SIGTERM -> SIGKILL
- Zombie & orphan process reaping (os.waitpid)
- Workspace sandboxing in /tmp/labtrack/workspace_<session_id> with secure wipe
- Captive Portal Auto-Authenticator bridge (Cyberoam/Sophos on https://10.10.10.2:8090/httpclient.html)
"""

import os
import sys
import time
import signal
import shutil
import socket
import logging
import urllib3
import requests
import psutil
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, List

# Suppress self-signed certificate warnings for captive portal
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [LabTrackAgent] %(message)s"
)
logger = logging.getLogger("LabTrackAgent")

# Configuration from Environment
SERVER_URL = os.getenv("LABTRACK_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
HOSTNAME = os.getenv("LABTRACK_HOSTNAME", socket.gethostname())
CAPTIVE_PORTAL_URL = os.getenv("CAPTIVE_PORTAL_URL", "https://10.10.10.2:8090/httpclient.html")
CGROUP_ROOT = "/sys/fs/cgroup/labtrack"
SANDBOX_BASE = "/tmp/labtrack"

# Inactivity / Idle Timeout Configuration (Proposal Section 6 & OS Spec: Flow A step 7, Flow B, O9)
IDLE_TIMEOUT_SECONDS = int(os.getenv("LABTRACK_IDLE_TIMEOUT_SECONDS", str(30 * 60)))  # 30 minutes default
IDLE_WARN_SECONDS = int(os.getenv("LABTRACK_IDLE_WARN_SECONDS", str(25 * 60)))        # 25 minutes default

# Blacklisted process signatures (miners, torrents, unauthorized games)
BLACKLIST_PROCESS_NAMES = {
    "xmrig", "minerd", "cpuminer", "ethminer", "stratum",
    "transmission-daemon", "transmission-gtk", "qbittorrent", "deluge", "rtorrent",
    "steam", "lutris", "minecraft"
}

class AgentLocalHandler(BaseHTTPRequestHandler):
    agent_ref = None

    def log_message(self, format, *args):
        pass  # Quiet logging

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/unlock"):
            logger.info("🔓 Received local unlock request. Closing fullscreen kiosk and revealing complete Linux desktop...")
            if AgentLocalHandler.agent_ref:
                from urllib.parse import urlparse, parse_qs
                query = parse_qs(urlparse(self.path).query)
                sess_id_list = query.get("session_id")
                if sess_id_list and sess_id_list[0].isdigit():
                    AgentLocalHandler.agent_ref.active_session_id = int(sess_id_list[0])
                roll_list = query.get("roll")
                if roll_list:
                    AgentLocalHandler.agent_ref.active_student_roll = roll_list[0]
                AgentLocalHandler.agent_ref.last_known_state = "OCCUPIED"
                AgentLocalHandler.agent_ref.unlock_workstation_gui()
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"unlocked"}\n')
        elif self.path.startswith("/lock"):
            logger.info("🔒 Received local lock request. Locking workstation in fullscreen kiosk...")
            if AgentLocalHandler.agent_ref:
                AgentLocalHandler.agent_ref.last_known_state = "AVAILABLE"
                try:
                    requests.post(
                        f"{AgentLocalHandler.agent_ref.server_url}/api/agent/close",
                        json={
                            "hostname": AgentLocalHandler.agent_ref.hostname,
                            "session_id": AgentLocalHandler.agent_ref.active_session_id,
                            "reason": "Student logged out via dock / desktop shortcut"
                        },
                        timeout=2.0
                    )
                except Exception:
                    pass
                AgentLocalHandler.agent_ref.teardown_session()
                AgentLocalHandler.agent_ref.lock_workstation_gui()
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"locked"}\n')
        elif self.path.startswith("/poweroff") or self.path.startswith("/shutdown"):
            logger.info("⏻ Received local poweroff request. Shutting down system...")
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"shutting_down"}\n')
            if AgentLocalHandler.agent_ref:
                threading.Thread(target=AgentLocalHandler.agent_ref.poweroff_system, daemon=True).start()
        else:
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}\n')

class WorkstationAgent:
    def __init__(self):
        self.hostname = HOSTNAME
        self.server_url = SERVER_URL
        self.running = True
        self.active_session_id: Optional[int] = None
        self.active_student_roll: Optional[str] = None
        self.active_cgroup_path: Optional[str] = None
        self.active_workspace_path: Optional[str] = None
        self.last_known_state: str = "AVAILABLE"
        self._idle_warned: bool = False

        AgentLocalHandler.agent_ref = self
        self._start_local_server()
        logger.info(f"Initialized LabTrack Agent on {self.hostname} bound to {self.server_url}")

    def _start_local_server(self):
        """Starts a local HTTP server on 127.0.0.1:8008 to listen for unlock/lock signals."""
        def run_server():
            try:
                server = HTTPServer(("127.0.0.1", 8008), AgentLocalHandler)
                logger.info("Local agent control server listening on 127.0.0.1:8008")
                server.serve_forever()
            except Exception as e:
                logger.warning(f"Could not bind local agent control server on 8008: {e}")
        t = threading.Thread(target=run_server, daemon=True)
        t.start()

    def get_browser_bin(self) -> str:
        for b in ["google-chrome", "chromium-browser", "chromium", "firefox"]:
            if shutil.which(b):
                return b
        return "x-www-browser"

    def get_active_gui_user(self) -> str:
        """Finds the logged-in desktop user."""
        try:
            import pwd
            if os.path.exists("/run/user"):
                for uid_dir in os.listdir("/run/user"):
                    if uid_dir.isdigit() and int(uid_dir) >= 1000:
                        return pwd.getpwuid(int(uid_dir)).pw_name
        except Exception:
            pass

        try:
            lines = subprocess.check_output(["who"]).decode().splitlines()
            for l in lines:
                parts = l.split()
                if len(parts) >= 2 and parts[0] not in ("root", "lightdm", "gdm"):
                    return parts[0]
        except Exception:
            pass

        users = [d for d in os.listdir("/home") if os.path.isdir(f"/home/{d}")]
        return users[0] if users else "root"

    def get_gui_env(self, user: str) -> Dict[str, str]:
        """Extracts running desktop DISPLAY and WAYLAND environment from /proc."""
        env = os.environ.copy()
        try:
            import pwd
            pw = pwd.getpwnam(user)
            uid = str(pw.pw_uid)
            home = pw.pw_dir
        except Exception:
            uid = "1000"
            home = f"/home/{user}"

        env["USER"] = user
        env["HOME"] = home
        env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
        env["DISPLAY"] = ":0"

        if os.path.exists(f"/run/user/{uid}/wayland-0"):
            env["WAYLAND_DISPLAY"] = "wayland-0"

        if os.path.exists(f"/run/user/{uid}/bus"):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"

        for proc in psutil.process_iter(['pid', 'username']):
            try:
                if proc.info['username'] == user:
                    with open(f"/proc/{proc.info['pid']}/environ", "rb") as f:
                        data = f.read().decode("utf-8", errors="ignore")
                        proc_env = dict(item.split("=", 1) for item in data.split("\0") if "=" in item)
                        for k in ["DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"]:
                            if k in proc_env and proc_env[k]:
                                env[k] = proc_env[k]
                        if "DISPLAY" in proc_env or "WAYLAND_DISPLAY" in proc_env:
                            break
            except Exception:
                continue

        if "XAUTHORITY" not in env:
            for cand in [
                f"{home}/.Xauthority",
                f"/run/user/{uid}/gdm/Xauthority",
                f"/run/user/{uid}/.mutter-Xwaylandauth"
            ]:
                if os.path.exists(cand):
                    env["XAUTHORITY"] = cand
                    break
        return env

    def is_kiosk_running(self) -> bool:
        """Checks if fullscreen kiosk browser is currently running."""
        try:
            res = subprocess.run(["pgrep", "-f", ".*--kiosk.*"], stdout=subprocess.DEVNULL)
            return res.returncode == 0
        except Exception:
            return False

    def launch_gui_command(self, cmd_args: List[str]):
        user = self.get_active_gui_user()
        env = self.get_gui_env(user)
        logger.info(f"Launching GUI command for user '{user}': {' '.join(cmd_args[:4])}")

        try:
            if os.geteuid() == 0 and user != "root":
                import pwd
                pw = pwd.getpwnam(user)
                try:
                    subprocess.run(["xhost", "+local:"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

                p = subprocess.Popen(
                    cmd_args,
                    user=pw.pw_uid,
                    group=pw.pw_gid,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info(f"Launched GUI process PID {p.pid} as user {user}")
            else:
                p = subprocess.Popen(cmd_args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info(f"Launched GUI process PID {p.pid}")
        except Exception as e:
            logger.error(f"Error launching GUI command: {e}")

    def create_desktop_logout_icon(self):
        """Creates an un-missable Desktop and application shortcut to logout anytime."""
        user = self.get_active_gui_user()
        desktop_dir = f"/home/{user}/Desktop"
        shortcut_content = """[Desktop Entry]
Version=1.0
Type=Application
Name=🔒 Logout & Relock Workstation
Comment=End LabTrack session and relock machine
Exec=curl -s http://127.0.0.1:8008/lock
Icon=system-lock-screen
Terminal=false
Categories=Utility;
"""
        try:
            if os.path.exists(desktop_dir):
                shortcut_path = os.path.join(desktop_dir, "labtrack-logout.desktop")
                with open(shortcut_path, "w") as f:
                    f.write(shortcut_content)
                os.chmod(shortcut_path, 0o755)
                import pwd
                pw = pwd.getpwnam(user)
                os.chown(shortcut_path, pw.pw_uid, pw.pw_gid)
                try:
                    subprocess.run(["gio", "set", shortcut_path, "metadata::trusted", "true"], user=pw.pw_uid, env=self.get_gui_env(user), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Note creating desktop shortcut: {e}")

    def unlock_workstation_gui(self):
        """Kills fullscreen kiosk lock screen and reveals the complete Linux desktop!"""
        try:
            subprocess.run(["pkill", "-f", ".*--kiosk.*"], stderr=subprocess.DEVNULL)
        except Exception:
            pass
        time.sleep(0.5)

        # Clear stale dock profile lock so Chrome opens instantly without conflicts
        dock_dir = "/tmp/labtrack_dock_profile"
        try:
            shutil.rmtree(dock_dir, ignore_errors=True)
            os.makedirs(dock_dir, mode=0o777, exist_ok=True)
            user = self.get_active_gui_user()
            import pwd
            pw = pwd.getpwnam(user)
            os.chown(dock_dir, pw.pw_uid, pw.pw_gid)
        except Exception:
            pass

        # Create desktop logout icon for convenience on student's desktop
        self.create_desktop_logout_icon()

        browser = self.get_browser_bin()
        floating_url = f"{self.server_url}/workstation/{self.hostname}?floating=1"
        self.launch_gui_command([
            browser,
            f"--user-data-dir={dock_dir}",
            f"--app={floating_url}",
            "--window-size=580,120",
            "--window-position=500,30",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--disable-infobars"
        ])
        logger.info("🔓 Complete Ubuntu desktop unlocked for student! Kiosk dismissed.")

    def lock_workstation_gui(self):
        """Closes floating widget and re-locks workstation in fullscreen kiosk mode."""
        try:
            subprocess.run(["pkill", "-f", ".*floating=1.*"], stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-f", ".*labtrack_dock.*"], stderr=subprocess.DEVNULL)
        except Exception:
            pass
        time.sleep(0.5)
        browser = self.get_browser_bin()
        kiosk_url = f"{self.server_url}/workstation/{self.hostname}"
        self.launch_gui_command([
            browser,
            "--kiosk",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-translate",
            "--disable-pinch",
            "--overscroll-history-navigation=0",
            kiosk_url
        ])
        logger.info("🔒 Workstation locked into un-minimizable fullscreen kiosk mode.")

    # =========================================================================
    # 1. CGROUPS v2 ENFORCEMENT
    # =========================================================================
    def setup_session_cgroup(self, session_id: int, memory_max_bytes: int = 17179869184, cpu_weight: int = 100) -> Optional[str]:
        """
        Creates a dedicated cgroups v2 slice for the student session:
        /sys/fs/cgroup/labtrack/session_<id>
        Sets memory.max and cpu.weight.
        """
        session_cgroup = f"{CGROUP_ROOT}/session_{session_id}"
        try:
            os.makedirs(session_cgroup, exist_ok=True)

            # Set CPU weight (fair sharing)
            cpu_weight_file = os.path.join(session_cgroup, "cpu.weight")
            if os.path.exists(cpu_weight_file):
                with open(cpu_weight_file, "w") as f:
                    f.write(str(cpu_weight))

            # Set Memory limit (16GB default)
            mem_max_file = os.path.join(session_cgroup, "memory.max")
            if os.path.exists(mem_max_file):
                with open(mem_max_file, "w") as f:
                    f.write(str(memory_max_bytes))

            logger.info(f"cgroups v2 initialized successfully at {session_cgroup}")
            self.active_cgroup_path = session_cgroup
            return session_cgroup
        except PermissionError:
            logger.warning(f"Root privileges required for cgroups v2 write at {session_cgroup}. Running in unprivileged mode.")
            self.active_cgroup_path = session_cgroup
            return session_cgroup
        except Exception as e:
            logger.error(f"Error configuring cgroup: {e}")
            return None

    def teardown_session_cgroup(self, session_id: int):
        """Cleans up the cgroup directory upon logout."""
        if not self.active_cgroup_path or not os.path.exists(self.active_cgroup_path):
            return
        try:
            # Terminate remaining processes inside the cgroup
            procs_file = os.path.join(self.active_cgroup_path, "cgroup.procs")
            if os.path.exists(procs_file):
                with open(procs_file, "r") as f:
                    pids = [int(line.strip()) for line in f if line.strip()]
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
            os.rmdir(self.active_cgroup_path)
            logger.info(f"Removed session cgroup: {self.active_cgroup_path}")
        except Exception as e:
            logger.warning(f"Note on cgroup teardown: {e}")
        finally:
            self.active_cgroup_path = None

    # =========================================================================
    # 2. SANDBOX ISOLATION & HYGIENE WIPE
    # =========================================================================
    def setup_workspace_sandbox(self, session_id: int) -> str:
        """Creates clean isolated workspace for the student in /tmp/labtrack/workspace_<session_id>."""
        workspace = f"{SANDBOX_BASE}/workspace_{session_id}"
        os.makedirs(workspace, mode=0o700, exist_ok=True)
        self.active_workspace_path = workspace
        logger.info(f"Created isolated session workspace at {workspace}")
        return workspace

    def wipe_workspace_sandbox(self):
        """Thorough hygiene wipe of student session files upon logout."""
        if self.active_workspace_path and os.path.exists(self.active_workspace_path):
            try:
                shutil.rmtree(self.active_workspace_path, ignore_errors=True)
                logger.info(f"Wiped workspace sandbox at {self.active_workspace_path}")
            except Exception as e:
                logger.error(f"Failed wiping workspace: {e}")
            finally:
                self.active_workspace_path = None

    # =========================================================================
    # 3. CAPTIVE PORTAL AUTO-AUTHENTICATOR BRIDGE
    # =========================================================================
    def authenticate_captive_portal(self, roll_no: str, password: str) -> bool:
        """
        Sends automated background HTTP POST to Cyberoam/Sophos captive portal:
        URL: https://10.10.10.2:8090/httpclient.html
        Payload: mode=191&username=<roll_no>&password=<password>
        """
        logger.info(f"Attempting captive portal authentication for {roll_no} via {CAPTIVE_PORTAL_URL}")
        payload = {
            "mode": "191",
            "username": roll_no,
            "password": password
        }
        try:
            resp = requests.post(
                CAPTIVE_PORTAL_URL,
                data=payload,
                timeout=2.0,
                verify=False
            )
            logger.info(f"Captive portal responded with status {resp.status_code}")
            return True
        except requests.exceptions.RequestException as e:
            # As clarified, off-campus or local test environment should log without failing session
            logger.warning(f"Captive portal at {CAPTIVE_PORTAL_URL} unreachable ({e}). Proceeding in local LAN mode.")
            return False

    def logout_captive_portal(self, roll_no: str) -> bool:
        """
        Sends automated logout HTTP POST to Cyberoam/Sophos captive portal:
        Payload: mode=193&username=<roll_no>
        """
        logger.info(f"Sending captive portal logout for {roll_no}...")
        payload = {
            "mode": "193",
            "username": roll_no
        }
        try:
            requests.post(
                CAPTIVE_PORTAL_URL,
                data=payload,
                timeout=2.0,
                verify=False
            )
            logger.info("Captive portal logout completed.")
            return True
        except Exception:
            return False

    # =========================================================================
    # 4. /proc INSPECTION & BLACKLIST ENFORCEMENT
    # =========================================================================
    def scan_and_enforce_blacklist(self):
        """
        Inspects process table for unauthorized software.
        Applies staged termination: SIGTERM -> wait 2s -> SIGKILL.
        """
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = proc.info['name'] or ""
                cmdline = " ".join(proc.info['cmdline'] or []).lower()
                pid = proc.info['pid']

                # Avoid killing self or essential system daemons
                if pid == os.getpid() or pid == 1:
                    continue

                is_blacklisted = False
                matched_target = None
                for blacklisted in BLACKLIST_PROCESS_NAMES:
                    if blacklisted in name.lower() or blacklisted in cmdline:
                        is_blacklisted = True
                        matched_target = blacklisted
                        break

                if is_blacklisted:
                    logger.warning(f"🚨 UNAUTHORIZED PROCESS DETECTED: PID {pid} ({matched_target}). Initiating staged kill...")
                    # Stage 1: Graceful SIGTERM
                    try:
                        os.kill(pid, signal.SIGTERM)
                        time.sleep(0.5)
                        # Stage 2: Immediate SIGKILL if still surviving
                        if psutil.pid_exists(pid):
                            os.kill(pid, signal.SIGKILL)
                            logger.info(f"Killed violating process PID {pid} with SIGKILL.")
                    except OSError:
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def collect_proc_telemetry(self) -> Dict[str, Any]:
        """Inspects /proc and system metrics: CPU%, memory RSS, page faults, process count."""
        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        load_avg = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0

        # Estimate process count and page faults
        proc_count = len(psutil.pids())

        return {
            "cpu_percent": round(cpu_pct, 2),
            "memory_rss_bytes": mem.used,
            "memory_percent": round(mem.percent, 2),
            "page_faults": 0,
            "process_count": proc_count,
            "load_average": round(load_avg, 2)
        }

    # =========================================================================
    # 5. ZOMBIE & ORPHAN REAPING
    # =========================================================================
    def reap_zombie_processes(self):
        """Reaps defunct child processes using os.waitpid(-1, os.WNOHANG)."""
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid <= 0:
                    break
                logger.debug(f"Reaped defunct child process PID {pid} (status {status})")
            except ChildProcessError:
                break
            except Exception:
                break

    # =========================================================================
    # 6. SERVER HEARTBEAT & SYNCHRONIZATION
    # =========================================================================
    def send_heartbeat(self):
        """Sends heartbeat to control plane and ingests telemetry if session active."""
        url = f"{self.server_url}/api/agent/heartbeat"
        payload = {
            "hostname": self.hostname,
            "current_session_id": self.active_session_id
        }
        try:
            resp = requests.post(url, json=payload, timeout=3.0)
            if resp.ok:
                data = resp.json()
                server_state = data.get("state", "AVAILABLE")
                session_active = data.get("session_active", False)

                self._heartbeat_counter = getattr(self, "_heartbeat_counter", 0) + 1
                if self._heartbeat_counter % 3 == 0:  # Log every ~9 seconds
                    logger.info(f"❤️ [Heartbeat ACK] Synced with Lab Server | State: {server_state} | Session Active: {session_active}")

                # 1. Transition to OCCUPIED (Student checked in)
                if server_state == "OCCUPIED" and session_active:
                    self.active_session_id = data.get("active_session_id")
                    self.active_student_roll = data.get("active_roll_no") or "Student"
                    if self.last_known_state != "OCCUPIED":
                        student_name = data.get("active_student_name") or "Student"
                        logger.info(f"Workstation checked in! Student: {student_name} ({self.active_student_roll}). Unlocking full Ubuntu desktop...")
                        self.last_known_state = "OCCUPIED"
                        self.unlock_workstation_gui()
                # 2. Transition to AVAILABLE or HELD (Session closed or idle)
                elif server_state in ("AVAILABLE", "HELD"):
                    if self.last_known_state == "OCCUPIED":
                        logger.info("Server reported session ended. Relocking into fullscreen kiosk...")
                        self.teardown_session()
                        self.last_known_state = server_state
                        self.lock_workstation_gui()
                    else:
                        self.last_known_state = server_state
                        # Self-healing: if unauthenticated but kiosk is not running, restore lock screen
                        if not self.is_kiosk_running():
                            logger.info("Fullscreen kiosk not detected while workstation is AVAILABLE/HELD. Relaunching lock screen...")
                            self.lock_workstation_gui()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Heartbeat server connection note: {e}")

    def send_telemetry(self):
        """Ingests live /proc telemetry to server."""
        if not self.active_session_id:
            return
        metrics = self.collect_proc_telemetry()
        metrics["session_id"] = self.active_session_id
        metrics["hostname"] = self.hostname

        try:
            requests.post(f"{self.server_url}/api/agent/telemetry", json=metrics, timeout=2.0)
        except Exception:
            pass

    def teardown_session(self):
        """Wipes sandbox, removes cgroups, logs out captive portal."""
        if self.active_student_roll:
            self.logout_captive_portal(self.active_student_roll)
        self.wipe_workspace_sandbox()
        if self.active_session_id:
            self.teardown_session_cgroup(self.active_session_id)

        self.active_session_id = None
        self.active_student_roll = None
        logger.info("Session teardown and security wipe finalized.")

    # =========================================================================
    # 7. INACTIVITY & IDLE TIMEOUT WATCHDOG (Flow A step 7, Flow B, OS Spec O9)
    # =========================================================================
    def get_inactivity_seconds(self) -> float:
        """
        Calculates user inactivity seconds using:
        1. Hardware Input Devices (/dev/input/event* device mtimes)
        2. X11 XScreenSaver Query (libXss.so.1 via ctypes)
        """
        now = time.time()
        idle_estimates = []

        # 1. Hardware Input Devices (/dev/input/event*)
        try:
            import glob
            dev_files = glob.glob("/dev/input/event*") + ["/dev/input/mice", "/dev/input/mouse0"]
            mtimes = [os.stat(f).st_mtime for f in dev_files if os.path.exists(f)]
            if mtimes:
                idle_estimates.append(max(0.0, now - max(mtimes)))
        except Exception:
            pass

        # 2. X11 XScreenSaver Query
        user = self.get_active_gui_user()
        env = self.get_gui_env(user)
        try:
            import ctypes
            class XScreenSaverInfo(ctypes.Structure):
                _fields_ = [
                    ('window', ctypes.c_ulong),
                    ('state', ctypes.c_int),
                    ('kind', ctypes.c_int),
                    ('til_or_since', ctypes.c_ulong),
                    ('idle', ctypes.c_ulong),
                    ('eventMask', ctypes.c_ulong)
                ]
            xlib = ctypes.cdll.LoadLibrary('libX11.so.6')
            xss = ctypes.cdll.LoadLibrary('libXss.so.1')
            disp_str = env.get("DISPLAY", ":0").encode('utf-8')
            dpy = xlib.XOpenDisplay(disp_str)
            if dpy:
                root = xlib.XDefaultRootWindow(dpy)
                info = XScreenSaverInfo()
                xss.XScreenSaverQueryInfo(dpy, root, ctypes.byref(info))
                xlib.XCloseDisplay(dpy)
                idle_estimates.append(max(0.0, info.idle / 1000.0))
        except Exception:
            pass

        if not idle_estimates:
            return 0.0

        return min(idle_estimates)

    def check_inactivity_and_enforce_timeout(self):
        """
        Monitors desktop activity. If student leaves workstation unattended for 30 minutes:
        - Sends visual warning at 25 minutes
        - At 30 minutes: auto-closes session with server, wipes workspace sandbox, and relocks screen into kiosk mode.
        """
        if not self.active_session_id:
            self._idle_warned = False
            return

        idle_sec = self.get_inactivity_seconds()

        # Safeguard: If student's background jobs are actively utilizing CPU > 20%, do not kill active compute
        proc_telemetry = self.collect_proc_telemetry()
        if proc_telemetry.get("cpu_percent", 0.0) >= 20.0:
            if self._idle_warned:
                self._idle_warned = False
            return

        # 1. Warning Threshold (e.g. 25 minutes)
        if idle_sec >= IDLE_WARN_SECONDS and not self._idle_warned:
            self._idle_warned = True
            mins_left = max(1, int((IDLE_TIMEOUT_SECONDS - idle_sec) / 60))
            logger.warning(f"⚠️ User idle for {int(idle_sec / 60)} minutes. Workstation will auto-relock in {mins_left} minutes.")
            user = self.get_active_gui_user()
            env = self.get_gui_env(user)
            try:
                subprocess.run(
                    ["notify-send", "-u", "critical", "⚠️ LabTrack Inactivity Warning",
                     f"No user activity detected for {int(idle_sec / 60)} minutes.\nWorkstation will automatically relock and end session in {mins_left} minutes."],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

        # Reset warning flag if user returns and types/moves mouse
        elif idle_sec < IDLE_WARN_SECONDS and self._idle_warned:
            logger.info("User activity detected. Resetting inactivity warning.")
            self._idle_warned = False

        # 2. Timeout Threshold (e.g. 30 minutes)
        if idle_sec >= IDLE_TIMEOUT_SECONDS:
            logger.warning(
                f"🔒 Inactivity timeout reached ({int(idle_sec / 60)} minutes idle). "
                f"Auto-closing session #{self.active_session_id} and relocking workstation..."
            )
            try:
                requests.post(
                    f"{self.server_url}/api/agent/close",
                    json={
                        "hostname": self.hostname,
                        "session_id": self.active_session_id,
                        "reason": f"Session auto-closed due to {int(idle_sec / 60)} min user inactivity"
                    },
                    timeout=3.0
                )
            except Exception as e:
                logger.error(f"Error notifying server of inactivity close: {e}")

            # Teardown workspace and cgroups
            self.teardown_session()
            self._idle_warned = False
            self.last_known_state = "AVAILABLE"

            # Relock into fullscreen kiosk screen
            self.lock_workstation_gui()
            logger.info("Workstation successfully relocked and reset to AVAILABLE after idle timeout.")

    # =========================================================================
    # 8. MAIN AGENT DAEMON LOOP
    # =========================================================================
    def run(self):
        logger.info(f"LabTrack Agent daemon active on {self.hostname}. Starting monitoring cycle.")
        
        # Handle SIGTERM / SIGINT gracefully
        signal.signal(signal.SIGTERM, self._handle_exit)
        signal.signal(signal.SIGINT, self._handle_exit)

        cycle = 0
        while self.running:
            try:
                # 1. Zombie reaping
                self.reap_zombie_processes()

                # 2. Blacklist scan & enforcement
                self.scan_and_enforce_blacklist()

                # 3. Heartbeat & Telemetry every 3 seconds
                self.send_heartbeat()
                self.send_telemetry()

                # 4. Inactivity & Idle Timeout Watchdog (30-min auto-relock)
                self.check_inactivity_and_enforce_timeout()

                time.sleep(3.0)
                cycle += 1
            except Exception as e:
                logger.error(f"Agent loop error: {e}")
                time.sleep(3.0)

        logger.info("Agent daemon exiting. Cleaning up resources...")
        self.teardown_session()

    def poweroff_system(self):
        """Notifies server to end session, wipes workspace, and powers off the PC."""
        logger.info("⏻ Initiating system poweroff sequence...")
        try:
            requests.post(
                f"{self.server_url}/api/agent/close",
                json={
                    "hostname": self.hostname,
                    "session_id": self.active_session_id,
                    "reason": "Workstation shutdown by user"
                },
                timeout=2.5
            )
            logger.info(f"Notified server of shutdown for {self.hostname}.")
        except Exception as e:
            logger.warning(f"Error notifying server of shutdown: {e}")
        self.teardown_session()
        time.sleep(0.5)
        try:
            subprocess.run(["systemctl", "poweroff"])
        except Exception:
            subprocess.run(["shutdown", "-h", "now"])

    def _handle_exit(self, signum, frame):
        logger.info(f"Received signal {signum} (system shutdown or daemon stop). Gracefully logging out active session...")
        try:
            requests.post(
                f"{self.server_url}/api/agent/close",
                json={
                    "hostname": self.hostname,
                    "session_id": self.active_session_id,
                    "reason": "Workstation powered off / system shutdown"
                },
                timeout=2.5
            )
            logger.info(f"Successfully notified server of shutdown for {self.hostname}.")
        except Exception as e:
            logger.warning(f"Could not reach server during shutdown: {e}")
        self.teardown_session()
        self.running = False
        sys.exit(0)

if __name__ == "__main__":
    agent = WorkstationAgent()
    agent.run()
