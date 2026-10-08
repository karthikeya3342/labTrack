import os
from pydantic import BaseModel

class Settings(BaseModel):
    PROJECT_NAME: str = "LabTrack"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    HOST: str = os.getenv("LABTRACK_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("LABTRACK_PORT", "8000"))
    
    # PostgreSQL Configuration
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "labtrack")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", os.getenv("USER", "karthikeya"))
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "/home/karthikeya/labTrack/.pg_socket")
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"postgresql://{POSTGRES_USER}@127.0.0.1:{POSTGRES_PORT}/labtrack?host={POSTGRES_HOST}"
    )

    # JWT Authentication
    JWT_SECRET: str = os.getenv("JWT_SECRET", "labtrack_super_secret_jwt_key_2026_x86_production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

    # Grace Period & Policies
    RESERVATION_GRACE_MINUTES: int = 15
    WALKIN_MAX_HOURS: int = 2
    GPU_MIN_RUN_HOURS_FOR_PREEMPTION: float = 1.0
    
    # Captive Portal Cyberoam/Sophos bridge
    CAPTIVE_PORTAL_URL: str = os.getenv("CAPTIVE_PORTAL_URL", "https://10.10.10.2:8090/httpclient.html")
    CAPTIVE_PORTAL_TIMEOUT_SEC: float = 2.0

settings = Settings()
