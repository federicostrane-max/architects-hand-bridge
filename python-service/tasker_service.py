"""
Tasker Service - FastAPI wrapper for OAGI
Supports all three Lux modes: Actor, Thinker, and Tasker
Runs locally and receives requests from Architect's Hand Bridge
"""

import asyncio
import os
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# OAGI imports - all from main module
try:
    from oagi import Actor, TaskerAgent, AsyncPyautoguiActionHandler, AsyncScreenshotMaker
    OAGI_AVAILABLE = True
except ImportError as e:
    print(f"Warning: OAGI import failed: {e}")
    OAGI_AVAILABLE = False


# Request/Response models
class TaskRequest(BaseModel):
    api_key: str
    task_description: str
    todos: List[str]
    start_url: Optional[str] = None
    max_steps: int = 60
    reflection_interval: int = 20
    model: str = "lux-actor-1"
    temperature: float = 0.1
    mode: str = "tasker"  # 'direct', 'tasker', 'actor', 'thinker'


class TaskResponse(BaseModel):
    success: bool
    message: str
    completed_todos: int
    total_todos: int
    error: Optional[str] = None
    execution_summary: Optional[dict] = None


class StatusResponse(BaseModel):
    status: str
    oagi_available: bool
    version: str = "2.1.0"


# Global state
current_task = None
is_running = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    print("=" * 50)
    print("Tasker Service Starting...")
    print(f"OAGI Available: {OAGI_AVAILABLE}")
    print("Supported modes: actor, thinker, tasker, direct")
    print("=" * 50)
    yield
    print("Tasker Service Shutting Down...")


# Create FastAPI app
app = FastAPI(
    title="Tasker Service",
    description="Local service for OAGI execution (Actor/Thinker/Tasker modes)",
    version="2.1.0",
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
    """Execute a task using the appropriate OAGI agent based on mode"""
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
        # Set API key
        os.environ["OAGI_API_KEY"] = request.api_key
        
        # Route based on mode
        mode = request.mode.lower()
        
        if mode in ['direct', 'actor', 'thinker']:
            # Direct execution - use Actor without TaskerAgent
            return await execute_direct_mode(request)
        else:
            # Tasker mode - use TaskerAgent with todos
            return await execute_tasker_mode(request)
        
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


async def execute_direct_mode(request: TaskRequest) -> TaskResponse:
    """Execute using Actor directly (for Actor/Thinker modes)"""
    
    print(f"\n{'='*50}")
    print(f"[Direct Mode] Executing: {request.task_description}")
    print(f"Model: {request.model}")
    print(f"Max Steps: {request.max_steps}")
    print(f"{'='*50}\n")
    
    try:
        # Determine model based on mode
        model = request.model
        if request.mode == 'thinker' and 'thinker' not in model:
            model = 'lux-thinker-1'
        elif request.mode == 'actor' and 'actor' not in model:
            model = 'lux-actor-1'
        
        # Create Actor - only pass supported parameters
        actor = Actor(
            api_key=request.api_key,
            model=model
        )
        
        # Initialize task with max_steps
        actor.init_task(
            task_desc=request.task_description,
            max_steps=request.max_steps
        )
        
        # Create handlers
        action_handler = AsyncPyautoguiActionHandler()
        image_provider = AsyncScreenshotMaker()
        
        # Execute
        print("Starting Actor execution...")
        success = await actor.execute(
            request.task_description,
            action_handler,
            image_provider
        )
        
        print(f"\nDirect task {'completed successfully' if success else 'failed'}\n")
        
        return TaskResponse(
            success=success,
            message="Task completed successfully" if success else "Task failed",
            completed_todos=1 if success else 0,
            total_todos=1
        )
        
    except Exception as e:
        print(f"Direct mode error: {e}")
        raise


async def execute_tasker_mode(request: TaskRequest) -> TaskResponse:
    """Execute using TaskerAgent with todos (for Tasker mode)"""
    
    print(f"\n{'='*50}")
    print(f"[Tasker Mode] Executing: {request.task_description}")
    print(f"Todos: {len(request.todos)}")
    for i, todo in enumerate(request.todos):
        print(f"  {i+1}. {todo}")
    print(f"Model: {request.model}")
    print(f"Max Steps: {request.max_steps}")
    print(f"Reflection Interval: {request.reflection_interval}")
    print(f"{'='*50}\n")
    
    try:
        # Create TaskerAgent
        tasker = TaskerAgent(
            api_key=request.api_key,
            model=request.model,
            max_steps=request.max_steps,
            reflection_interval=request.reflection_interval
        )
        
        # Set task with todos
        tasker.set_task(
            task=request.task_description,
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
        completed = 0
        
        if memory and hasattr(memory, 'todos'):
            completed = sum(1 for t in memory.todos if getattr(t, 'status', '').lower() == 'completed')
        elif success:
            completed = len(request.todos)
        
        print(f"\nTask {'completed successfully' if success else 'failed'}")
        print(f"Completed {completed}/{len(request.todos)} todos\n")
        
        return TaskResponse(
            success=success,
            message="Task completed successfully" if success else "Task failed",
            completed_todos=completed,
            total_todos=len(request.todos)
        )
        
    except Exception as e:
        print(f"Tasker mode error: {e}")
        raise


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
        "version": "2.1.0",
        "oagi_available": OAGI_AVAILABLE,
        "supported_modes": ["actor", "thinker", "tasker", "direct"],
        "endpoints": [
            "GET /status - Check service status",
            "POST /execute - Execute a task",
            "POST /stop - Stop current task"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "=" * 50)
    print("  TASKER SERVICE v2.1")
    print("  Supports: Actor | Thinker | Tasker modes")
    print("=" * 50 + "\n")
    
    uvicorn.run(
        app, 
        host="127.0.0.1", 
        port=8765,
        log_level="info"
    )
