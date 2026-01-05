#!/usr/bin/env python3
"""
FastAPI server for WhisperSubs

Provides REST API endpoints for audio/video transcription services.
"""
import os
import sys
import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import WhisperSubs
from whisper_subs import WhisperSubs, add_job, get_jobs, list_jobs as get_job_list
import model

# Create the FastAPI app
app = FastAPI(
    title="WhisperSubs API",
    description="API for transcribing audio from various sources using Whisper",
    version="1.0.0"
)

# Thread pool for running WhisperSubs processing in the background
executor = ThreadPoolExecutor(max_workers=1)

# Dictionary to track ongoing tasks
task_status = {}

class TranscriptionRequest(BaseModel):
    source: str = Field(..., description="URL or file path to transcribe")
    model_name: str = Field("large", description="Whisper model name (tiny, base, small, medium, large, etc.)")
    device: str = Field("cpu", description="Device to use (cpu, cuda)")
    compute_type: str = Field("int8", description="Compute type (int8, float16)")
    force: bool = Field(False, description="Force transcription even if already processed")
    ignore_subs: bool = Field(False, description="Ignore existing subtitles")
    sub_lang: Optional[str] = Field(None, description="Subtitle language code")
    run_mpv: bool = Field(False, description="Run player in background")
    force_retry: bool = Field(False, description="Force retry transcription even if already completed")


class TaskResponse(BaseModel):
    task_id: str
    status: str
    source: str
    model_name: str
    created_at: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


@app.get("/")
def read_root():
    return {"message": "WhisperSubs API", "status": "running"}


@app.get("/models", response_model=List[str])
def get_available_models():
    """Get list of available Whisper models"""
    return model.MODEL_NAMES


@app.post("/transcribe", response_model=TaskResponse)
def start_transcription(request: TranscriptionRequest, background_tasks: BackgroundTasks):
    """Start a new transcription task"""
    # Validate model name
    if request.model_name not in model.MODEL_NAMES:
        valid_model_name = model.getName(request.model_name)
        if not valid_model_name or valid_model_name not in model.MODEL_NAMES:
            raise HTTPException(status_code=400, detail=f"Invalid model name. Valid models: {model.MODEL_NAMES}")
        request.model_name = valid_model_name

    # Generate a unique task ID
    task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    
    # Create task status entry
    task_status[task_id] = {
        "status": "pending",
        "source": request.source,
        "model_name": request.model_name,
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "progress": None,
        "result": None,
        "error": None
    }

    # Create a WhisperSubs processor
    def run_transcription():
        try:
            task_status[task_id]["status"] = "processing"
            processor = WhisperSubs(
                model_name=request.model_name,
                device=request.device,
                compute_type=request.compute_type,
                force=request.force,
                ignore_subs=request.ignore_subs,
                sub_lang=request.sub_lang,
                run_mpv=request.run_mpv,
                force_retry=request.force_retry
            )
            
            # Process the source
            job = add_job(request.source, request.model_name)
            processor.process(job)
            
            # Update task status on completion
            task_status[task_id]["status"] = "completed"
            task_status[task_id]["completed_at"] = datetime.now().isoformat()
            task_status[task_id]["result"] = {
                "source": request.source,
                "output_directory": os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs")
            }
        except Exception as e:
            task_status[task_id]["status"] = "failed"
            task_status[task_id]["error"] = str(e)
            task_status[task_id]["completed_at"] = datetime.now().isoformat()
            print(f"Error processing task {task_id}: {e}")

    # Run the transcription in a thread
    background_tasks.add_task(run_transcription)
    
    return TaskResponse(
        task_id=task_id,
        status="pending",
        source=request.source,
        model_name=request.model_name,
        created_at=task_status[task_id]["created_at"]
    )


@app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str):
    """Get the status of a transcription task"""
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskStatusResponse(
        task_id=task_id,
        status=task_status[task_id]["status"],
        progress=task_status[task_id].get("progress"),
        result=task_status[task_id].get("result"),
        error=task_status[task_id].get("error"),
        created_at=task_status[task_id]["created_at"],
        completed_at=task_status[task_id].get("completed_at")
    )


@app.get("/tasks", response_model=List[TaskStatusResponse])
def list_tasks():
    """List all tasks"""
    tasks = []
    for task_id, details in task_status.items():
        tasks.append(TaskStatusResponse(
            task_id=task_id,
            status=details["status"],
            progress=details.get("progress"),
            result=details.get("result"),
            error=details.get("error"),
            created_at=details["created_at"],
            completed_at=details.get("completed_at")
        ))
    return tasks


@app.get("/jobs", response_model=List[Dict[str, Any]])
def list_jobs():
    """List all transcription jobs"""
    jobs = get_jobs()
    return jobs


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)