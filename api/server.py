#!/usr/bin/env python3
"""
FastAPI server for WhisperSubs

Provides REST API endpoints for audio/video transcription services.
Enhanced with WebSocket support, advanced options, and task management.
"""
import os
import sys
import json
import asyncio
import shutil
import socketio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import datetime
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import WhisperSubs
from whisper_subs import WhisperSubs, add_job, get_jobs, list_jobs as get_job_list
import model

# Create the FastAPI app
app = FastAPI(
    title="WhisperSubs API",
    description="API for transcribing audio from various sources using Whisper",
    version="2.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Socket.IO server for real-time progress updates
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, app)

# Thread pool for running WhisperSubs processing in the background
executor = ThreadPoolExecutor(max_workers=5)  # Increased for concurrent tasks

# Task queue for chained/batch processing
task_queue = asyncio.Queue()
task_queue_lock = asyncio.Lock()

# Dictionary to track ongoing tasks
task_status = {}
task_lock = threading.Lock()

# Batch processing state
batch_status = {}
batch_lock = threading.Lock()

# Output directory
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs")

class TranscriptionRequest(BaseModel):
    source: str = Field(..., description="URL or file path to transcribe")
    model_name: str = Field("large", description="Whisper model name")
    device: str = Field("cpu", description="Device (cpu, cuda)")
    compute_type: str = Field("int8", description="Compute type")
    
    # Transcription options
    force: bool = Field(False, description="Force transcription")
    replace_subs: bool = Field(False, description="Replace existing subtitles")
    backup_subs: bool = Field(True, description="Backup existing subtitles")
    retry: bool = Field(True, description="Retry with smaller models on failure")
    ignore_subs: bool = Field(False, description="Ignore existing subtitles")
    
    # Language and processing
    sub_lang: Optional[str] = Field(None, description="Subtitle language")
    language: Optional[str] = Field(None, description="Source audio language")
    run_mpv: bool = Field(False, description="Run MPV player")
    
    # VAD settings
    vad_filter: Optional[bool] = Field(None, description="Enable VAD filter")
    vad_silence_duration: Optional[int] = Field(None, description="VAD min silence (ms)")
    
    # Diarization
    diarization: bool = Field(False, description="Enable speaker diarization")
    min_speakers: Optional[int] = Field(None, description="Min speakers")
    max_speakers: Optional[int] = Field(None, description="Max speakers")
    
    # Advanced
    temperature: Optional[float] = Field(None, description="Sampling temperature")
    start_time: Optional[str] = Field(None, description="Start time (HH:MM:SS or seconds)")
    end_time: Optional[str] = Field(None, description="End time (HH:MM:SS or seconds)")
    cpu_threads: Optional[int] = Field(None, description="CPU thread count")
    
    # MPV IPC
    mpv_ipc: bool = Field(False, description="Enable MPV IPC subtitle reload")
    mpv_socket: Optional[str] = Field("/tmp/mpvsocket", description="MPV socket path")


class TranscriptionRequestAdvanced(TranscriptionRequest):
    """Extended request with batch processing support"""
    batch_id: Optional[str] = Field(None, description="Batch ID for grouping tasks")
    priority: int = Field(5, ge=1, le=10, description="Task priority (1=lowest, 10=highest)")


class BatchTranscriptionRequest(BaseModel):
    """Request for batch/chained transcription of multiple sources"""
    sources: List[str] = Field(..., description="List of URLs or file paths to transcribe")
    model_name: str = Field("large", description="Whisper model name")
    device: str = Field("cpu", description="Device (cpu, cuda)")
    compute_type: str = Field("int8", description="Compute type")
    
    # Transcription options (apply to all)
    force: bool = Field(False)
    replace_subs: bool = Field(False)
    backup_subs: bool = Field(True)
    retry: bool = Field(True)
    ignore_subs: bool = Field(False)
    
    # Language and processing
    sub_lang: Optional[str] = Field(None)
    language: Optional[str] = Field(None)
    run_mpv: bool = Field(False)
    
    # VAD settings
    vad_filter: Optional[bool] = Field(None)
    vad_silence_duration: Optional[int] = Field(None)
    
    # Diarization
    diarization: bool = Field(False)
    min_speakers: Optional[int] = Field(None)
    max_speakers: Optional[int] = Field(None)
    
    # Advanced
    temperature: Optional[float] = Field(None)
    start_time: Optional[str] = Field(None)
    end_time: Optional[str] = Field(None)
    cpu_threads: Optional[int] = Field(None)
    
    # MPV IPC
    mpv_ipc: bool = Field(False)
    mpv_socket: Optional[str] = Field("/tmp/mpvsocket")
    
    # Batch options
    batch_id: Optional[str] = Field(None, description="Custom batch ID (auto-generated if not provided)")
    concurrent: int = Field(2, ge=1, le=5, description="Number of concurrent transcriptions")
    priority: int = Field(5, ge=1, le=10, description="Batch priority")


class BatchStatusResponse(BaseModel):
    batch_id: str
    total: int
    pending: int
    processing: int
    completed: int
    failed: int
    cancelled: int
    created_at: str
    completed_at: Optional[str] = None
    tasks: List[str]  # List of task IDs


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
async def start_transcription(request: TranscriptionRequest, background_tasks: BackgroundTasks):
    """Start a new transcription task with advanced options"""
    # Validate model name
    if request.model_name not in model.MODEL_NAMES:
        valid_model_name = model.getName(request.model_name)
        if not valid_model_name or valid_model_name not in model.MODEL_NAMES:
            raise HTTPException(status_code=400, detail=f"Invalid model name. Valid models: {model.MODEL_NAMES}")
        request.model_name = valid_model_name

    # Generate a unique task ID
    task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

    # Create task status entry with extended info
    with task_lock:
        task_status[task_id] = {
            "status": "pending",
            "source": request.source,
            "model_name": request.model_name,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "progress": None,
            "result": None,
            "error": None,
            "options": request.dict()
        }

    # Create a WhisperSubs processor with all options
    def run_transcription():
        try:
            with task_lock:
                task_status[task_id]["status"] = "processing"
            
            # Build WhisperSubs with all parameters
            processor = WhisperSubs(
                model_name=request.model_name,
                device=request.device,
                compute_type=request.compute_type,
                force=request.force,
                ignore_subs=request.ignore_subs,
                sub_lang=request.sub_lang,
                run_mpv=request.run_mpv,
                force_retry=request.retry,
                # VAD settings
                vad_filter=request.vad_filter,
                vad_min_silence_duration=request.vad_silence_duration,
                # Diarization
                diarization=request.diarization,
                min_speakers=request.min_speakers,
                max_speakers=request.max_speakers,
                # Advanced
                temperature=request.temperature,
                start_time=request.start_time,
                end_time=request.end_time,
                # MPV IPC
                mpv_ipc=request.mpv_ipc,
                mpv_socket=request.mpv_socket
            )

            # Process the source
            job = add_job(request.source, request.model_name)
            processor.process(request.source)

            # Update task status on completion
            with task_lock:
                task_status[task_id]["status"] = "completed"
                task_status[task_id]["completed_at"] = datetime.now().isoformat()
                task_status[task_id]["result"] = {
                    "source": request.source,
                    "output_directory": OUTPUT_DIR
                }
            
        except Exception as e:
            with task_lock:
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


@app.post("/transcribe/batch", response_model=BatchStatusResponse)
async def start_batch_transcription(request: BatchTranscriptionRequest, background_tasks: BackgroundTasks):
    """Start batch transcription of multiple sources with concurrent processing"""
    import uuid
    
    batch_id = request.batch_id or f"batch_{uuid.uuid4().hex[:8]}"
    task_ids = []
    
    # Create batch status entry
    with batch_lock:
        batch_status[batch_id] = {
            "total": len(request.sources),
            "pending": len(request.sources),
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "tasks": []
        }
    
    # Create individual transcription requests for each source
    for idx, source in enumerate(request.sources):
        task_id = f"task_{batch_id}_{idx}_{datetime.now().strftime('%H%M%S_%f')}"
        task_ids.append(task_id)
        
        # Create task status with batch reference
        with task_lock:
            task_status[task_id] = {
                "status": "queued",
                "source": source,
                "model_name": request.model_name,
                "batch_id": batch_id,
                "priority": request.priority,
                "created_at": datetime.now().isoformat(),
                "completed_at": None,
                "progress": None,
                "result": None,
                "error": None
            }
        
        # Add to batch task list
        with batch_lock:
            batch_status[batch_id]["tasks"].append(task_id)
    
    # Worker function to process tasks with concurrency limit
    async def process_batch():
        semaphore = asyncio.Semaphore(request.concurrent)
        
        async def process_single_task(task_id: str, source: str):
            async with semaphore:
                await asyncio.get_event_loop().run_in_executor(
                    executor,
                    run_single_transcription,
                    task_id,
                    source,
                    request,
                    batch_id
                )
        
        # Create tasks for all sources
        tasks = [
            process_single_task(task_id, source)
            for task_id, source in zip(task_ids, request.sources)
        ]
        
        # Run all tasks with concurrency limit
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Update batch status when all tasks complete
        with batch_lock:
            batch_status[batch_id]["completed_at"] = datetime.now().isoformat()
        
        # Emit batch completion
        await sio.emit('batch_completed', {'batch_id': batch_id})
    
    def run_single_transcription(task_id: str, source: str, request: BatchTranscriptionRequest, batch_id: str):
        """Run single transcription within batch"""
        try:
            with task_lock:
                task_status[task_id]["status"] = "processing"
                batch_status[batch_id]["processing"] += 1
                batch_status[batch_id]["pending"] -= 1
            
            processor = WhisperSubs(
                model_name=request.model_name,
                device=request.device,
                compute_type=request.compute_type,
                force=request.force,
                ignore_subs=request.ignore_subs,
                sub_lang=request.sub_lang,
                run_mpv=request.run_mpv,
                force_retry=request.retry,
                vad_filter=request.vad_filter,
                vad_min_silence_duration=request.vad_silence_duration,
                diarization=request.diarization,
                min_speakers=request.min_speakers,
                max_speakers=request.max_speakers,
                temperature=request.temperature,
                start_time=request.start_time,
                end_time=request.end_time,
                mpv_ipc=request.mpv_ipc,
                mpv_socket=request.mpv_socket
            )
            
            job = add_job(source, request.model_name)
            processor.process(source)
            
            with task_lock:
                task_status[task_id]["status"] = "completed"
                task_status[task_id]["completed_at"] = datetime.now().isoformat()
                batch_status[batch_id]["completed"] += 1
                batch_status[batch_id]["processing"] -= 1
            
        except Exception as e:
            with task_lock:
                task_status[task_id]["status"] = "failed"
                task_status[task_id]["error"] = str(e)
                task_status[task_id]["completed_at"] = datetime.now().isoformat()
                batch_status[batch_id]["failed"] += 1
                if batch_status[batch_id]["processing"] > 0:
                    batch_status[batch_id]["processing"] -= 1
            print(f"Error in batch task {task_id}: {e}")
    
    # Start batch processing in background
    background_tasks.add_task(process_batch)
    
    return BatchStatusResponse(
        batch_id=batch_id,
        total=batch_status[batch_id]["total"],
        pending=batch_status[batch_id]["pending"],
        processing=batch_status[batch_id]["processing"],
        completed=batch_status[batch_id]["completed"],
        failed=batch_status[batch_id]["failed"],
        cancelled=batch_status[batch_id]["cancelled"],
        created_at=batch_status[batch_id]["created_at"],
        tasks=batch_status[batch_id]["tasks"]
    )


@app.get("/batch/{batch_id}", response_model=BatchStatusResponse)
def get_batch_status(batch_id: str):
    """Get status of a batch transcription"""
    if batch_id not in batch_status:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    batch = batch_status[batch_id]
    return BatchStatusResponse(
        batch_id=batch_id,
        total=batch["total"],
        pending=batch["pending"],
        processing=batch["processing"],
        completed=batch["completed"],
        failed=batch["failed"],
        cancelled=batch["cancelled"],
        created_at=batch["created_at"],
        completed_at=batch.get("completed_at"),
        tasks=batch["tasks"]
    )


@app.get("/batches", response_model=List[BatchStatusResponse])
def list_batches():
    """List all batch transcriptions"""
    batches = []
    for batch_id, batch in batch_status.items():
        batches.append(BatchStatusResponse(
            batch_id=batch_id,
            total=batch["total"],
            pending=batch["pending"],
            processing=batch["processing"],
            completed=batch["completed"],
            failed=batch["failed"],
            cancelled=batch["cancelled"],
            created_at=batch["created_at"],
            completed_at=batch.get("completed_at"),
            tasks=batch["tasks"]
        ))
    return batches


@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time task progress updates"""
    await sio.connect(websocket)
    try:
        # Join room for this task
        await sio.enter_room(task_id)
        
        # Send current status
        if task_id in task_status:
            await websocket.send_json(task_status[task_id])
        
        # Keep connection alive
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})
            
    except WebSocketDisconnect:
        await sio.leave_room(task_id)
    except Exception as e:
        print(f"WebSocket error: {e}")


@app.get("/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    """Cancel a transcription task"""
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task_status[task_id]["status"] in ["completed", "failed"]:
        raise HTTPException(status_code=400, detail="Task already completed")
    
    with task_lock:
        task_status[task_id]["status"] = "cancelled"
        task_status[task_id]["completed_at"] = datetime.now().isoformat()
    
    return {"message": f"Task {task_id} cancelled"}


@app.get("/subtitles/{filename}")
def get_subtitle(filename: str):
    """Download a subtitle file"""
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Subtitle not found")
    return FileResponse(file_path, media_type="text/plain", filename=filename)


@app.get("/subtitles/list")
def list_subtitles(source: Optional[str] = None):
    """List available subtitle files"""
    subtitles = []
    if os.path.exists(OUTPUT_DIR):
        for root, dirs, files in os.walk(OUTPUT_DIR):
            for file in files:
                if file.endswith('.srt'):
                    rel_path = os.path.relpath(os.path.join(root, file), OUTPUT_DIR)
                    if source is None or source.lower() in rel_path.lower():
                        subtitles.append({
                            "filename": file,
                            "path": rel_path,
                            "created": datetime.fromtimestamp(os.path.getctime(os.path.join(root, file))).isoformat()
                        })
    return sorted(subtitles, key=lambda x: x['created'], reverse=True)


@app.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    """Delete a completed/failed task from history"""
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task_status[task_id]["status"] not in ["completed", "failed", "cancelled"]:
        raise HTTPException(status_code=400, detail="Can only delete completed/failed tasks")
    
    with task_lock:
        del task_status[task_id]
    
    return {"message": f"Task {task_id} deleted"}


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
    """Health check endpoint with system info"""
    import psutil
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
        "active_tasks": len([t for t in task_status.values() if t["status"] == "processing"])
    }


if __name__ == "__main__":
    import uvicorn
    # Use socket_app instead of app for Socket.IO support
    uvicorn.run(socket_app, host="0.0.0.0", port=8000)