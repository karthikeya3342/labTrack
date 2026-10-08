import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.core.database import init_db_pool, close_db_pool
from backend.app.api import auth, pcs, reservations, agent, admin, scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB pool
    await init_db_pool()
    yield
    # Shutdown: Close DB pool
    await close_db_pool()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="LabTrack - University Computer Lab Resource Management & Scheduling Engine",
    lifespan=lifespan
)

# Enable CORS for local LAN client workstations and web portal
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(pcs.router, prefix=settings.API_V1_STR)
app.include_router(reservations.router, prefix=settings.API_V1_STR)
app.include_router(agent.router, prefix=settings.API_V1_STR)
app.include_router(admin.router, prefix=settings.API_V1_STR)
app.include_router(scheduler.router, prefix=settings.API_V1_STR)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

# Serve Web Portal (Student & Admin Dashboard)
@app.get("/", response_class=HTMLResponse)
async def serve_portal():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return HTMLResponse("<h1>LabTrack Web Portal</h1><p>Frontend file not found.</p>")

# Serve Workstation Kiosk Greeter / Lock Screen for client PCs
@app.get("/workstation/{hostname}", response_class=HTMLResponse)
async def serve_workstation_screen(hostname: str):
    screen_path = os.path.join(FRONTEND_DIR, "workstation_screen.html")
    if os.path.exists(screen_path):
        return FileResponse(screen_path, media_type="text/html")
    return HTMLResponse(f"<h1>LabTrack Workstation Screen for {hostname}</h1>")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "LabTrack Control Plane", "version": settings.VERSION}
