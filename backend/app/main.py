import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.core.database import init_db_pool, close_db_pool
from backend.app.api import auth, pcs, reservations, agent, admin, scheduler, clubs, faculty

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
app.include_router(clubs.router, prefix=settings.API_V1_STR)
app.include_router(faculty.router, prefix=settings.API_V1_STR)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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

@app.get("/install-agent.sh", response_class=PlainTextResponse)
async def serve_agent_installer():
    script_path = os.path.join(PROJECT_ROOT, "scripts/install_agent_client.sh")
    if os.path.exists(script_path):
        with open(script_path, "r") as f:
            return PlainTextResponse(f.read())
    return PlainTextResponse("#!/bin/sh\necho 'Not found'\n")

@app.get("/agent/labtrack_agent.py", response_class=PlainTextResponse)
async def serve_agent_script():
    agent_path = os.path.join(PROJECT_ROOT, "agent/labtrack_agent.py")
    if os.path.exists(agent_path):
        with open(agent_path, "r") as f:
            return PlainTextResponse(f.read())
    return PlainTextResponse("# Not found\n")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "LabTrack Control Plane", "version": settings.VERSION}
