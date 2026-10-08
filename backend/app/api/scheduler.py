from fastapi import APIRouter
from backend.app.core.intelligent_scheduler import run_simulation_comparison, DynamicTaskPoolScheduler, TaskPoolItem

router = APIRouter(prefix="/scheduler", tags=["Intelligent Scheduler"])

@router.post("/simulate-comparison")
async def simulate_scheduler_comparison():
    """
    Simulates laboratory scheduling comparing:
    - Baseline FCFS
    - Intelligent Heuristic GA (VPPM from Chao He & Shi Cheng 2025)
    Returns equipment utilization improvements (+16.3% to +34.6%), GA convergence, Gantt chart, and TaskPool items.
    """
    result = run_simulation_comparison()
    return result

@router.get("/taskpool")
async def get_dynamic_taskpool():
    pool = DynamicTaskPoolScheduler()
    sample_tasks = [
        TaskPoolItem("TASK-101", "STU001", "Alice Johnson", "Senior Project", 120.0, 1, 32.0, 8, waiting_time_min=45.0, running_time_min=75.0, is_running=True, assigned_lab_id=3, assigned_pc="AI-PC-01"),
        TaskPoolItem("TASK-102", "STU002", "Bob Smith", "Practice", 60.0, 0, 16.0, 4, waiting_time_min=15.0, running_time_min=30.0, is_running=True, assigned_lab_id=1, assigned_pc="COMP-PC-03"),
        TaskPoolItem("TASK-103", "STU003", "Charlie Brown", "Exam", 90.0, 1, 48.0, 12, waiting_time_min=80.0, running_time_min=0.0, is_running=False),
        TaskPoolItem("TASK-104", "STU004", "Diana Prince", "Coursework", 45.0, 0, 16.0, 4, waiting_time_min=10.0, running_time_min=0.0, is_running=False),
        TaskPoolItem("TASK-105", "STU005", "Ethan Hunt", "Research Experiment", 180.0, 2, 64.0, 16, waiting_time_min=110.0, running_time_min=0.0, is_running=False)
    ]
    for t in sample_tasks:
        pool.add_task(t)
    return pool.get_ranked_queue()
