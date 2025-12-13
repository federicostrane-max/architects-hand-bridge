"""
Tasker Service - FastAPI wrapper for OAGI TaskerAgent
Runs locally and receives requests from Architect's Hand Bridge
"""

import asyncio
import base64
import os
import sys
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# OAGI imports
try:
    from oagi import Actor
    from oagi.agent.tasker import TaskerAgent
    from oagi.handlers.pyautogui_action_handler import AsyncPyautoguiActionHandler
    from oagi.image_providers.screenshot import AsyncScreenshotMaker
    OAGI_AVAILABLE = True
except ImportError as e:
    print(f"Warning: OAGI import failed: {e}")
    OAGI_AVAILABLE = False


# Request/Response models
class TaskRequest(BaseModel):
    api_key: str
    task_description: str
    todos: list[str]
    start_url: Optional[str] = None
    max_steps: int = 60
    reflection_interval: int = 20


class TaskResponse(BaseModel):
    success: bool
    message: str
    completed_todos: int
    total_todos: int
    error: Optional[str] = None


class StatusResponse(BaseModel):
    status: str
    oagi_available: bool
    version: str = "1.0.0"


# Global state
current_task = None
is_running = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    print("=" * 50)
    print("Tasker Service Starting...")
    print(f"OAGI Available: {OAGI_AVAILABLE}")
    print("=" * 50)
    yield
    print("Tasker Service Shutting Down...")


# Create FastAPI app
app = FastAPI(
    title="Tasker Service",
    description="Local service for OAGI TaskerAgent execution",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for Electron app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Check if service is running and OAGI is available"""
    return StatusResponse(
        status="running" if not is_running else "busy",
        oagi_available=OAGI_AVAILABLE
    )


@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    """Execute a task using TaskerAgent"""
    global is_running, current_task
    
    if not OAGI_AVAILABLE:
        raise HTTPException(
            status_code=500, 
            detail="OAGI library not available. Please install with: pip install oagi"
        )
    
    if is_running:
        raise HTTPException(
            status_code=409,
            detail="Another task is currently running"
        )
    
    is_running = True
    current_task = request.task_description
    
    try:
        print(f"\n{'='*50}")
        print(f"Executing Task: {request.task_description}")
        print(f"Todos: {len(request.todos)}")
        for i, todo in enumerate(request.todos):
            print(f"  {i+1}. {todo}")
        print(f"{'='*50}\n")
        
        # Set API key
        os.environ["OAGI_API_KEY"] = request.api_key
        
        # Create TaskerAgent
        tasker = TaskerAgent(
            api_key=request.api_key,
            model="lux-actor-1",
            max_steps=request.max_steps,
            reflection_interval=request.reflection_interval,
            temperature=0.1
        )
        
        # Set task with todos
        tasker.set_task(
            instruction=request.task_description,
            todos=request.todos
        )
        
        # Create handlers
        action_handler = AsyncPyautoguiActionHandler()
        image_provider = AsyncScreenshotMaker()
        
        # Execute
        print("Starting TaskerAgent execution...")
        success = await tasker.execute(
            request.task_description,
            action_handler,
            image_provider
        )
        
        # Get results
        memory = tasker.get_memory() if hasattr(tasker, 'get_memory') else None
        completed = sum(1 for t in (memory.todos if memory else []) if getattr(t, 'status', '') == 'completed')
        
        print(f"\nTask {'completed successfully' if success else 'failed'}")
        print(f"Completed {completed}/{len(request.todos)} todos\n")
        
        return TaskResponse(
            success=success,
            message="Task completed successfully" if success else "Task failed",
            completed_todos=completed,
            total_todos=len(request.todos)
        )
        
    except Exception as e:
        print(f"Error executing task: {e}")
        import traceback
        traceback.print_exc()
        return TaskResponse(
            success=False,
            message="Task failed with error",
            completed_todos=0,
            total_todos=len(request.todos),
            error=str(e)
        )
        
    finally:
        is_running = False
        current_task = None


@app.post("/stop")
async def stop_task():
    """Stop the currently running task"""
    global is_running, current_task
    
    if not is_running:
        return {"message": "No task running"}
    
    # TODO: Implement graceful stop
    is_running = False
    current_task = None
    
    return {"message": "Task stop requested"}


@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "Tasker Service",
        "version": "1.0.0",
        "oagi_available": OAGI_AVAILABLE,
        "endpoints": [
            "GET /status - Check service status",
            "POST /execute - Execute a task with TaskerAgent",
            "POST /stop - Stop current task"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "=" * 50)
    print("  TASKER SERVICE")
    print("  Local OAGI TaskerAgent Wrapper")
    print("=" * 50 + "\n")
    
    uvicorn.run(
        app, 
        host="127.0.0.1", 
        port=8765,
        log_level="info"
    )
