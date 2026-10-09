from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- Auth Schemas ---
class LoginRequest(BaseModel):
    roll_no: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]

# --- Workstation Schemas ---
class PCSpecs(BaseModel):
    cpu: Optional[str] = None
    ram_gb: Optional[int] = None
    gpu: Optional[str] = None
    os: Optional[str] = None

class PCResponse(BaseModel):
    id: int
    hostname: str
    lab_id: int
    lab_name: Optional[str] = None
    ip_address: Optional[str] = None
    state: str
    specifications: Dict[str, Any]
    last_heartbeat: Optional[datetime] = None
    active_reservation: Optional[Dict[str, Any]] = None
    active_session: Optional[Dict[str, Any]] = None
    latest_telemetry: Optional[Dict[str, Any]] = None

class LockStateResponse(BaseModel):
    hostname: str
    state: str  # AVAILABLE, HELD, OCCUPIED, MAINTENANCE
    lab_id: int
    lab_name: str
    reserved_student_name: Optional[str] = None
    reserved_roll_no: Optional[str] = None
    grace_deadline: Optional[datetime] = None
    remaining_grace_seconds: Optional[int] = None
    active_session: Optional[Dict[str, Any]] = None
    latest_telemetry: Optional[Dict[str, Any]] = None
    is_club_event: Optional[bool] = False
    club_name: Optional[str] = None
    club_slug: Optional[str] = None
    club_logo_url: Optional[str] = None
    event_title: Optional[str] = None
    event_id: Optional[int] = None
    message: Optional[str] = None

# --- Reservation Schemas ---
class AdvanceBookingRequest(BaseModel):
    pc_id: Optional[int] = None
    lab_id: Optional[int] = None
    start_time: datetime
    end_time: datetime
    task_type: str = "Practice"
    software_required: List[str] = []
    deadline: Optional[datetime] = None
    notes: Optional[str] = None

class WalkinBookingRequest(BaseModel):
    hostname: str
    task_type: str = "Practice"
    software_required: List[str] = []

# --- Agent Schemas ---
class AgentCheckinRequest(BaseModel):
    hostname: str
    roll_no: str
    password: str
    cgroup_path: Optional[str] = None
    workspace_path: Optional[str] = None

class AgentCheckinResponse(BaseModel):
    session_id: int
    reservation_id: Optional[int] = None
    pc_id: int
    student_id: int
    student_name: str
    roll_no: str
    status: str
    message: str

class AgentCloseRequest(BaseModel):
    session_id: Optional[int] = None
    hostname: Optional[str] = None
    reason: str = "Student Logout"

class AgentHeartbeatRequest(BaseModel):
    hostname: str
    ip_address: Optional[str] = None
    current_session_id: Optional[int] = None

class TelemetrySampleRequest(BaseModel):
    session_id: int
    hostname: str
    cpu_percent: float = 0.0
    memory_rss_bytes: int = 0
    memory_percent: float = 0.0
    page_faults: int = 0
    process_count: int = 0
    load_average: float = 0.0
