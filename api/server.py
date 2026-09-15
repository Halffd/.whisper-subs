#!/usr/bin/env python3
"""
FastAPI server for WhisperSubs

Provides REST API endpoints for audio/video transcription services.
Enhanced with WebSocket support, advanced options, task management, and authentication.
"""

import os
import sys
import json
import asyncio
import shutil
import socketio
import secrets
import hashlib
import jwt
import time
import re
from typing import Optional, List, Dict, Any, Callable, Awaitable
from fastapi import (
    FastAPI,
    BackgroundTasks,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    Security,
    Form,
    Header,
)
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi.responses import (
    JSONResponse,
    FileResponse,
    StreamingResponse,
    HTMLResponse,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import datetime, timedelta
from pathlib import Path
import bcrypt

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import WhisperSubs
from whisper_subs import WhisperSubs, add_job, get_jobs, list_jobs as get_job_list
import model

# Import SRT tailer for real-time subtitle streaming
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from srt_tailer import SRTTailerManager, SRTTailer

# SRT file path registry: task_id -> {"srt": str, "unfinished": str}
srt_paths: Dict[str, Dict[str, str]] = {}
srt_paths_lock = threading.Lock()

# Media file path registry: task_id -> {"audio": str, "video": str}
media_paths: Dict[str, Dict[str, str]] = {}
media_paths_lock = threading.Lock()


def register_media_path(task_id: str, media_type: str, file_path: str):
    """Register a media file path for a task.

    Args:
        task_id: The task identifier
        media_type: "audio" or "video"
        file_path: Absolute path to the media file
    """
    with media_paths_lock:
        if task_id not in media_paths:
            media_paths[task_id] = {}
        media_paths[task_id][media_type] = file_path


def register_srt_path(task_id: str, path_type: str, file_path: str):
    """Register an SRT file path for a task.

    Args:
        task_id: The task identifier
        path_type: "srt" or "unfinished"
        file_path: Absolute path to the SRT file
    """
    with srt_paths_lock:
        if task_id not in srt_paths:
            srt_paths[task_id] = {}
        srt_paths[task_id][path_type] = file_path


# SRT tailer manager for real-time streaming
srt_tailer_manager = SRTTailerManager()

# Configuration
API_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "api_config.json")
JWT_SECRET_KEY = os.environ.get("WHISPER_JWT_SECRET", secrets.token_urlsafe(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Authentication schemes
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
API_KEY_QUERY = APIKeyQuery(name="api_key", auto_error=False)

# Create the FastAPI app
app = FastAPI(
    title="WhisperSubs API",
    description="API for transcribing audio from various sources using Whisper",
    version="3.0.0",
)


# Authentication Manager
class AuthManager:
    """Manage API keys, users, and JWT tokens"""

    def __init__(self, config_file: str):
        self.config_file = config_file
        self.lock = threading.Lock()
        self.token_blacklist: set = set()
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load or create API configuration"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass

        # Default configuration
        config: Dict[str, Any] = {
            "users": {
                "admin": {
                    "password_hash": bcrypt.hashpw(
                        "admin123".encode(), bcrypt.gensalt()
                    ).decode(),
                    "api_keys": [secrets.token_urlsafe(32)],
                    "role": "admin",
                    "created_at": datetime.now().isoformat(),
                }
            },
            "settings": {
                "require_auth": True,
                "allow_registration": False,
                "max_tasks_per_user": 10,
                "rate_limit_per_minute": 60,
            },
        }

        self._save_config(config)
        return config

    def _save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration to file"""
        with self.lock:
            with open(self.config_file, "w") as f:
                json.dump(config, f, indent=2)

    def verify_password(self, username: str, password: str) -> bool:
        """Verify user password"""
        if username not in self.config.get("users", {}):
            return False
        user = self.config["users"][username]
        return bcrypt.checkpw(password.encode(), user["password_hash"].encode())

    def create_api_key(self, username: str) -> Optional[str]:
        """Generate new API key for user"""
        if username not in self.config.get("users", {}):
            return None

        api_key = secrets.token_urlsafe(32)
        self.config["users"][username]["api_keys"].append(api_key)
        self._save_config(self.config)
        return api_key

    def verify_api_key(self, api_key: str) -> Optional[str]:
        """Verify API key and return username if valid"""
        for username, user_data in self.config.get("users", {}).items():
            if api_key in user_data.get("api_keys", []):
                return username
        return None

    def create_jwt_token(
        self, username: str, expires_hours: Optional[int] = None
    ) -> str:
        """Create JWT token for user"""
        if expires_hours is None:
            expires_hours = JWT_EXPIRATION_HOURS

        payload = {
            "sub": username,
            "exp": datetime.now() + timedelta(hours=expires_hours),
            "iat": datetime.now(),
            "type": "access",
        }
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    def verify_jwt_token(self, token: str) -> Optional[str]:
        """Verify JWT token and return username if valid"""
        if token in self.token_blacklist:
            return None

        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload.get("sub")
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def revoke_token(self, token: str) -> None:
        """Add token to blacklist"""
        self.token_blacklist.add(token)

    def get_user_info(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user information (without sensitive data)"""
        if username not in self.config.get("users", {}):
            return None

        user = self.config["users"][username]
        return {
            "username": username,
            "role": user.get("role", "user"),
            "created_at": user.get("created_at"),
            "api_keys_count": len(user.get("api_keys", [])),
        }

    def register_user(self, username: str, password: str) -> bool:
        """Register new user"""
        if not self.config.get("settings", {}).get("allow_registration", False):
            return False

        if username in self.config.get("users", {}):
            return False

        self.config["users"][username] = {
            "password_hash": bcrypt.hashpw(
                password.encode(), bcrypt.gensalt()
            ).decode(),
            "api_keys": [secrets.token_urlsafe(32)],
            "role": "user",
            "created_at": datetime.now().isoformat(),
        }
        self._save_config(self.config)
        return True

    def delete_api_key(self, username: str, api_key: str) -> bool:
        """Delete specific API key"""
        if username not in self.config.get("users", {}):
            return False

        keys = self.config["users"][username]["api_keys"]
        if api_key in keys:
            keys.remove(api_key)
            self._save_config(self.config)
            return True
        return False


# Global auth manager instance
auth_manager = AuthManager(API_CONFIG_FILE)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Authentication dependencies
async def get_current_user(
    api_key_header: Optional[str] = Security(API_KEY_HEADER),
    api_key_query: Optional[str] = Security(API_KEY_QUERY),
    authorization: Optional[str] = None,
) -> str:
    """Get current authenticated user from API key or JWT token"""
    # Try API key first (from header or query)
    api_key = api_key_header or api_key_query
    if api_key:
        username = auth_manager.verify_api_key(api_key)
        if username:
            return username

    # Try JWT token from Authorization header
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
            username = auth_manager.verify_jwt_token(token)
            if username:
                return username

    raise HTTPException(
        status_code=401, detail="Invalid or missing authentication credentials"
    )


async def get_current_user_optional(
    api_key_header: Optional[str] = Security(API_KEY_HEADER),
    api_key_query: Optional[str] = Security(API_KEY_QUERY),
) -> Optional[str]:
    """Get current user if authenticated, None otherwise"""
    api_key = api_key_header or api_key_query
    if api_key:
        return auth_manager.verify_api_key(api_key)
    return None


# Socket.IO server for real-time progress updates
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio, app)


# Enhanced thread pool with better resource management
class PriorityThreadPoolExecutor:
    """Thread pool executor with priority-based task scheduling"""

    def __init__(self, max_workers=5):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.active_tasks = {}
        self.task_lock = threading.Lock()
        self.cpu_usage = {}

    def submit(self, fn, *args, priority=5, task_id=None, **kwargs):
        """Submit task with priority (higher = more important)"""
        if task_id:
            with self.task_lock:
                self.active_tasks[task_id] = {
                    "priority": priority,
                    "started_at": datetime.now(),
                    "status": "queued",
                }

        def wrapper():
            if task_id:
                with self.task_lock:
                    self.active_tasks[task_id]["status"] = "running"
            try:
                return fn(*args, **kwargs)
            finally:
                if task_id:
                    with self.task_lock:
                        self.active_tasks.pop(task_id, None)

        return self.executor.submit(wrapper)

    def get_active_count(self):
        """Get number of currently running tasks"""
        with self.task_lock:
            return len(
                [t for t in self.active_tasks.values() if t["status"] == "running"]
            )

    def shutdown(self, wait=True):
        """Shutdown the executor"""
        self.executor.shutdown(wait=wait)


# Global executor with increased workers for better concurrency
executor = PriorityThreadPoolExecutor(max_workers=8)

# Task queue for batch processing with priority support
task_queue = asyncio.PriorityQueue()
task_queue_lock = asyncio.Lock()

# Rate limiting
rate_limit_lock = asyncio.Lock()
rate_limit_tasks = {}  # {client_ip: {'count': int, 'reset_at': datetime}}
RATE_LIMIT_MAX = 10  # Max concurrent tasks per client
RATE_LIMIT_WINDOW = 300  # 5 minutes

# Dictionary to track ongoing tasks
task_status = {}
task_lock = threading.Lock()

# Batch processing state
batch_status = {}
batch_lock = threading.Lock()

# Resource monitoring
resource_lock = threading.Lock()
resource_stats = {
    "cpu_percent": 0,
    "memory_percent": 0,
    "disk_usage": 0,
    "last_update": datetime.now(),
}

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
    vad_silence_duration: Optional[int] = Field(
        None, description="VAD min silence (ms)"
    )

    # Diarization
    diarization: bool = Field(False, description="Enable speaker diarization")
    min_speakers: Optional[int] = Field(None, description="Min speakers")
    max_speakers: Optional[int] = Field(None, description="Max speakers")

    # Advanced
    temperature: Optional[float] = Field(None, description="Sampling temperature")
    start_time: Optional[str] = Field(
        None, description="Start time (HH:MM:SS or seconds)"
    )
    end_time: Optional[str] = Field(None, description="End time (HH:MM:SS or seconds)")
    cpu_threads: Optional[int] = Field(None, description="CPU thread count")

    # MPV IPC
    mpv_ipc: bool = Field(False, description="Enable MPV IPC subtitle reload")
    mpv_socket: Optional[str] = Field("/tmp/mpvsocket", description="MPV socket path")


class TranscriptionRequestAdvanced(TranscriptionRequest):
    """Extended request with batch processing support"""

    batch_id: Optional[str] = Field(None, description="Batch ID for grouping tasks")
    priority: int = Field(
        5, ge=1, le=10, description="Task priority (1=lowest, 10=highest)"
    )


class BatchTranscriptionRequest(BaseModel):
    """Request for batch/chained transcription of multiple sources"""

    sources: List[str] = Field(
        ..., description="List of URLs or file paths to transcribe"
    )
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
    batch_id: Optional[str] = Field(
        None, description="Custom batch ID (auto-generated if not provided)"
    )
    concurrent: int = Field(
        3, ge=1, le=8, description="Number of concurrent transcriptions"
    )
    priority: int = Field(5, ge=1, le=10, description="Batch priority")
    auto_retry_failed: bool = Field(
        True, description="Automatically retry failed tasks with smaller models"
    )


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
    return {"message": "WhisperSubs API", "status": "running", "version": "3.0.0"}


# Authentication Endpoints
@app.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...)):
    """Login and get JWT token"""
    if not auth_manager.verify_password(username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = auth_manager.create_jwt_token(username)
    return {"access_token": token, "token_type": "bearer"}


@app.post("/auth/token/refresh")
async def refresh_token(current_user: str = Depends(get_current_user)):
    """Refresh JWT token"""
    token = auth_manager.create_jwt_token(current_user)
    return {"access_token": token, "token_type": "bearer"}


@app.post("/auth/logout")
async def logout(
    authorization: Optional[str] = None, current_user: str = Depends(get_current_user)
):
    """Logout and invalidate current token"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        auth_manager.revoke_token(token)
    return {"message": "Logged out successfully"}


@app.get("/auth/me")
async def get_me(current_user: str = Depends(get_current_user)):
    """Get current user information"""
    user_info = auth_manager.get_user_info(current_user)
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")
    return user_info


@app.post("/auth/api-keys")
async def create_api_key(current_user: str = Depends(get_current_user)):
    """Create new API key for current user"""
    api_key = auth_manager.create_api_key(current_user)
    if not api_key:
        raise HTTPException(status_code=500, detail="Failed to create API key")
    return {
        "api_key": api_key,
        "message": "Store this key securely - it won't be shown again",
    }


@app.get("/auth/api-keys")
async def list_api_keys(current_user: str = Depends(get_current_user)):
    """List API keys for current user (masked)"""
    user = auth_manager.config["users"].get(current_user, {})
    keys = user.get("api_keys", [])
    # Mask all but first 8 and last 8 characters
    masked_keys = [f"{k[:8]}...{k[-8:]}" if len(k) > 16 else "***" for k in keys]
    return {"api_keys": masked_keys, "count": len(keys)}


@app.delete("/auth/api-keys/{api_key}")
async def delete_api_key(api_key: str, current_user: str = Depends(get_current_user)):
    """Delete specific API key"""
    if auth_manager.delete_api_key(current_user, api_key):
        return {"message": "API key deleted"}
    raise HTTPException(status_code=404, detail="API key not found")


@app.post("/auth/register", status_code=201)
def register_user(username: str = Form(...), password: str = Form(...)):
    """Register new user (if registration is enabled)"""
    if len(username) < 3 or len(username) > 50:
        raise HTTPException(status_code=400, detail="Username must be 3-50 characters")

    if len(password) < 8:
        raise HTTPException(
            status_code=400, detail="Password must be at least 8 characters"
        )

    if not auth_manager.register_user(username, password):
        raise HTTPException(
            status_code=400, detail="Registration failed or username already exists"
        )

    # Auto-login after registration
    token = auth_manager.create_jwt_token(username)
    user_info = auth_manager.get_user_info(username)

    return {
        "message": "User registered successfully",
        "access_token": token,
        "user": user_info,
    }


@app.get("/models", response_model=List[str])
def get_available_models():
    """Get list of all available models (local + adapter)"""
    return model.ALL_MODEL_NAMES


@app.get("/models/local", response_model=List[str])
def get_local_models():
    """Get list of local Whisper models"""
    return model.MODEL_NAMES


@app.get("/models/adapters", response_model=List[str])
def get_adapter_models():
    """Get list of adapter-backed models"""
    return model.ADAPTER_MODEL_NAMES


@app.get("/adapters")
def get_adapters():
    """Get list of registered adapters with availability info"""
    ctx = model.TranscriptionContext()
    return ctx.list_available_adapters()


@app.get("/cache/stats")
def get_cache_stats():
    """Get audio cache statistics"""
    import audio_cache

    return audio_cache.stats()


@app.post("/transcribe", response_model=TaskResponse)
async def start_transcription(
    request: TranscriptionRequest,
    background_tasks: BackgroundTasks,
    current_user: str = Depends(get_current_user),
):
    """Start a new transcription task with advanced options"""
    # Validate model name
    if request.model_name not in model.ALL_MODEL_NAMES:
        valid_model_name = model.getName(request.model_name)
        if not valid_model_name or valid_model_name not in model.ALL_MODEL_NAMES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model name. Valid models: {model.ALL_MODEL_NAMES}",
            )
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
            "options": request.dict(),
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
                mpv_socket=request.mpv_socket,
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
                    "output_directory": OUTPUT_DIR,
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
        created_at=task_status[task_id]["created_at"],
    )


@app.post("/transcribe/batch", response_model=BatchStatusResponse)
async def start_batch_transcription(
    request: BatchTranscriptionRequest,
    background_tasks: BackgroundTasks,
    current_user: str = Depends(get_current_user),
):
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
            "tasks": [],
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
                "error": None,
            }

        # Add to batch task list
        with batch_lock:
            batch_status[batch_id]["tasks"].append(task_id)

    # Worker function to process tasks with concurrency limit and priority
    async def process_batch():
        # Use semaphore for concurrency control
        semaphore = asyncio.Semaphore(request.concurrent)

        # Sort sources by priority (could be extended for per-source priority)
        sorted_sources = list(enumerate(request.sources))

        async def process_single_task(idx: int, source: str):
            task_id = task_ids[idx]
            async with semaphore:
                # Check if task was cancelled
                with task_lock:
                    if task_status.get(task_id, {}).get("status") == "cancelled":
                        return

                # Run transcription in thread pool
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    executor.executor,  # Use underlying executor
                    run_single_transcription,
                    task_id,
                    source,
                    request,
                    batch_id,
                    idx,  # Pass index for retry logic
                )

        # Create tasks for all sources
        tasks = [process_single_task(idx, source) for idx, source in sorted_sources]

        # Run all tasks with concurrency limit and exception handling
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions that weren't caught
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                task_id = task_ids[idx]
                with task_lock:
                    if task_id in task_status:
                        task_status[task_id]["status"] = "failed"
                        task_status[task_id]["error"] = str(result)
                        task_status[task_id]["completed_at"] = (
                            datetime.now().isoformat()
                        )
                        batch_status[batch_id]["failed"] += 1
                        batch_status[batch_id]["processing"] = max(
                            0, batch_status[batch_id]["processing"] - 1
                        )
                print(f"Task {task_id} failed with exception: {result}")

        # Update batch status when all tasks complete
        with batch_lock:
            batch_status[batch_id]["completed_at"] = datetime.now().isoformat()
            # Recalculate counts from tasks
            completed = sum(
                1
                for tid in task_ids
                if task_status.get(tid, {}).get("status") == "completed"
            )
            failed = sum(
                1
                for tid in task_ids
                if task_status.get(tid, {}).get("status") == "failed"
            )
            batch_status[batch_id]["completed"] = completed
            batch_status[batch_id]["failed"] = failed
            batch_status[batch_id]["pending"] = 0
            batch_status[batch_id]["processing"] = 0

        # Emit batch completion
        await sio.emit(
            "batch_completed",
            {
                "batch_id": batch_id,
                "total": len(task_ids),
                "completed": batch_status[batch_id]["completed"],
                "failed": batch_status[batch_id]["failed"],
            },
        )

    def run_single_transcription(
        task_id: str,
        source: str,
        request: BatchTranscriptionRequest,
        batch_id: str,
        task_index: int,
    ):
        """Run single transcription within batch with retry support"""
        max_retries = 3 if request.auto_retry_failed else 1
        models_to_try = [request.model_name]

        # Add fallback models if retry is enabled
        if request.retry:
            fallback_models = ["medium", "small", "base"]
            models_to_try.extend(
                [m for m in fallback_models if m != request.model_name]
            )

        for attempt, model_name in enumerate(models_to_try[:max_retries]):
            try:
                with task_lock:
                    if attempt == 0:
                        task_status[task_id]["status"] = "processing"
                        batch_status[batch_id]["processing"] += 1
                        batch_status[batch_id]["pending"] -= 1
                    else:
                        task_status[task_id]["progress"] = (
                            f"Retry {attempt}/{max_retries} with {model_name}"
                        )

                processor = WhisperSubs(
                    model_name=model_name,
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
                    mpv_socket=request.mpv_socket,
                )

                job = add_job(source, model_name)
                processor.process(source)

                with task_lock:
                    task_status[task_id]["status"] = "completed"
                    task_status[task_id]["completed_at"] = datetime.now().isoformat()
                    task_status[task_id]["model_name"] = model_name
                    batch_status[batch_id]["completed"] += 1
                    batch_status[batch_id]["processing"] -= 1

                # Success - break retry loop
                break

            except Exception as e:
                is_last_attempt = (
                    attempt >= len(models_to_try) - 1 or attempt >= max_retries - 1
                )

                if is_last_attempt:
                    with task_lock:
                        task_status[task_id]["status"] = "failed"
                        task_status[task_id]["error"] = str(e)
                        task_status[task_id]["completed_at"] = (
                            datetime.now().isoformat()
                        )
                        batch_status[batch_id]["failed"] += 1
                        if batch_status[batch_id]["processing"] > 0:
                            batch_status[batch_id]["processing"] -= 1
                    print(f"Task {task_id} failed after {attempt + 1} attempts: {e}")
                else:
                    print(
                        f"Task {task_id} attempt {attempt + 1} failed, retrying with {models_to_try[attempt + 1]}..."
                    )
                    # Continue to next model

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
        tasks=batch_status[batch_id]["tasks"],
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
        tasks=batch["tasks"],
    )


@app.get("/batches", response_model=List[BatchStatusResponse])
def list_batches():
    """List all batch transcriptions"""
    batches = []
    for batch_id, batch in batch_status.items():
        batches.append(
            BatchStatusResponse(
                batch_id=batch_id,
                total=batch["total"],
                pending=batch["pending"],
                processing=batch["processing"],
                completed=batch["completed"],
                failed=batch["failed"],
                cancelled=batch["cancelled"],
                created_at=batch["created_at"],
                completed_at=batch.get("completed_at"),
                tasks=batch["tasks"],
            )
        )
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
                if file.endswith(".srt"):
                    rel_path = os.path.relpath(os.path.join(root, file), OUTPUT_DIR)
                    if source is None or source.lower() in rel_path.lower():
                        subtitles.append(
                            {
                                "filename": file,
                                "path": rel_path,
                                "created": datetime.fromtimestamp(
                                    os.path.getctime(os.path.join(root, file))
                                ).isoformat(),
                            }
                        )
    return sorted(subtitles, key=lambda x: x["created"], reverse=True)


# =============================================================================
# Real-time Subtitle Streaming Endpoints
# =============================================================================


@app.get("/api/v1/tasks/{task_id}/subtitles")
async def get_task_subtitles(task_id: str):
    """
    Get the current subtitle content for a task (growing or final).
    Returns the full SRT content as plain text.
    """
    with srt_paths_lock:
        if task_id not in srt_paths:
            raise HTTPException(
                status_code=404, detail="Task not found or subtitle path not registered"
            )
        paths = srt_paths[task_id]

    # Prefer finished SRT, fall back to unfinished
    srt_path = paths.get("srt") or paths.get("unfinished")
    if not srt_path or not os.path.exists(srt_path):
        raise HTTPException(status_code=404, detail="Subtitle file not found")

    return FileResponse(
        srt_path, media_type="text/plain", filename=os.path.basename(srt_path)
    )


@app.get("/api/v1/tasks/{task_id}/subtitles/stream")
async def stream_task_subtitles(task_id: str):
    """
    Stream subtitle segments as Server-Sent Events (SSE).

    Each event:
    - event: segment
    - data: JSON with {index, start, end, text}

    Final event:
    - event: done
    - data: {"task_id": "..."}
    """
    with srt_paths_lock:
        if task_id not in srt_paths:
            raise HTTPException(
                status_code=404, detail="Task not found or subtitle path not registered"
            )
        paths = srt_paths[task_id]

    unfinished_path = paths.get("unfinished")
    if not unfinished_path or not os.path.exists(unfinished_path):
        # Try finished file
        srt_path = paths.get("srt")
        if not srt_path or not os.path.exists(srt_path):
            raise HTTPException(status_code=404, detail="Subtitle file not found")

        # Return final content as single event
        async def final_stream():
            yield f"event: segment\ndata: {json.dumps({'final': True, 'path': srt_path})}\n\n"
            yield f"event: done\ndata: {json.dumps({'task_id': task_id})}\n\n"

        return StreamingResponse(final_stream(), media_type="text/event-stream")

    async def event_generator():
        queue = asyncio.Queue()

        async def on_segment(tid: str, block: "SRTBlock"):
            await queue.put(("segment", block.to_dict()))

        async def on_done(tid: str):
            await queue.put(("done", {"task_id": tid}))

        # Start tailing
        started = await srt_tailer_manager.start_tailing(
            task_id, paths["unfinished"], on_segment, on_done
        )
        if not started:
            # Already tailing or error
            yield f"event: error\ndata: {json.dumps({'error': 'Failed to start tailer'})}\n\n"
            return

        try:
            while True:
                event_type, data = await queue.get()
                if event_type == "segment":
                    yield f"event: segment\ndata: {json.dumps(data)}\n\n"
                elif event_type == "done":
                    yield f"event: done\ndata: {json.dumps(data)}\n\n"
                    break
        except asyncio.CancelledError:
            pass
        finally:
            srt_tailer_manager.stop_tailing(task_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/v1/tasks/{task_id}/subtitles/snapshot")
async def get_subtitles_snapshot(task_id: str):
    """
    Get current subtitle blocks as JSON array (for HTTP polling clients).
    Returns list of {index, start, end, text} objects.
    """
    with srt_paths_lock:
        if task_id not in srt_paths:
            raise HTTPException(
                status_code=404, detail="Task not found or subtitle path not registered"
            )
        paths = srt_paths[task_id]

    # Try unfinished first, then finished
    for path_key in ["unfinished", "srt"]:
        path = paths.get(path_key)
        if path and os.path.exists(path):
            tailer = SRTTailer(path)
            blocks = tailer.get_snapshot()
            return {
                "task_id": task_id,
                "source_path": path,
                "is_final": path_key == "srt",
                "blocks": [b.to_dict() for b in blocks],
                "count": len(blocks),
            }

    raise HTTPException(status_code=404, detail="Subtitle file not found")


# =============================================================================
# Media Streaming Endpoints (Audio/Video)
# =============================================================================


def _parse_range_header(range_header: Optional[str], file_size: int) -> tuple:
    """Parse Range header and return (start, end, content_length).

    Returns (0, file_size - 1, file_size) if no valid range header.
    """
    if not range_header or not range_header.startswith("bytes="):
        return 0, file_size - 1, file_size

    try:
        range_spec = range_header[6:]  # Remove "bytes="
        start_str, end_str = range_spec.split("-", 1)

        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1

        # Clamp to file bounds
        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))

        return start, end, end - start + 1
    except (ValueError, IndexError):
        return 0, file_size - 1, file_size


async def _stream_file(
    file_path: str,
    range_header: Optional[str] = None,
    media_type: str = "application/octet-stream",
    filename: Optional[str] = None,
):
    """Stream a file with Range request support."""
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Media file not found")

    file_size = os.path.getsize(file_path)
    start, end, content_length = _parse_range_header(range_header, file_size)

    async def file_iterator():
        chunk_size = 1024 * 1024  # 1MB chunks
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = content_length
            while remaining > 0:
                read_size = min(chunk_size, remaining)
                chunk = f.read(read_size)
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Range": f"bytes {start}-{end}/{file_size}",
    }

    if filename:
        headers["Content-Disposition"] = f'inline; filename="{filename}"'

    status_code = 206 if range_header else 200

    return StreamingResponse(
        file_iterator(),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


@app.get("/api/v1/media/audio/{cache_key}")
async def stream_cached_audio(
    cache_key: str,
    range: Optional[str] = Header(None, alias="Range"),
    current_user: str = Depends(get_current_user_optional),
):
    """
    Stream a cached audio file by cache key (SHA256 hash prefix).

    The cache key is the first 16 characters of the SHA256 hash of the source URL.
    Supports Range requests for seeking.
    """
    import audio_cache

    index = audio_cache._load_index()
    entry = index["entries"].get(cache_key)

    if not entry:
        raise HTTPException(status_code=404, detail="Audio not found in cache")

    audio_path = entry.get("path", "")
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Cached audio file not found")

    # Update LRU access time
    entry["mtime"] = time.time()
    audio_cache._save_index(index)

    # Determine media type from extension
    ext = os.path.splitext(audio_path)[1].lower()
    media_types = {
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }
    media_type = media_types.get(ext, "audio/mpeg")

    filename = os.path.basename(audio_path)
    return await _stream_file(audio_path, range, media_type, filename)


@app.get("/api/v1/media/video/{task_id}")
async def stream_task_video(
    task_id: str,
    range: Optional[str] = Header(None, alias="Range"),
    current_user: str = Depends(get_current_user_optional),
):
    """
    Stream the video file associated with a transcription task.

    Supports Range requests for seeking. The video file must have been
    registered via the media_paths registry (set during download).
    """
    with media_paths_lock:
        if task_id not in media_paths:
            raise HTTPException(
                status_code=404, detail="Task not found or media not registered"
            )
        paths = media_paths[task_id]

    video_path = paths.get("video")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    ext = os.path.splitext(video_path)[1].lower()
    media_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".m4v": "video/x-m4v",
    }
    media_type = media_types.get(ext, "video/mp4")

    filename = os.path.basename(video_path)
    return await _stream_file(video_path, range, media_type, filename)


@app.get("/api/v1/media/audio/{task_id}")
async def stream_task_audio(
    task_id: str,
    range: Optional[str] = Header(None, alias="Range"),
    current_user: str = Depends(get_current_user_optional),
):
    """
    Stream the audio file associated with a transcription task.

    Supports Range requests for seeking. The audio file must have been
    registered via the media_paths registry (set during download).
    """
    with media_paths_lock:
        if task_id not in media_paths:
            raise HTTPException(
                status_code=404, detail="Task not found or media not registered"
            )
        paths = media_paths[task_id]

    audio_path = paths.get("audio")
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")

    ext = os.path.splitext(audio_path)[1].lower()
    media_types = {
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }
    media_type = media_types.get(ext, "audio/mpeg")

    filename = os.path.basename(audio_path)
    return await _stream_file(audio_path, range, media_type, filename)


@app.get("/api/v1/media/info/{task_id}")
async def get_media_info(
    task_id: str,
    current_user: str = Depends(get_current_user_optional),
):
    """
    Get metadata about media files associated with a task.

    Returns file paths, sizes, durations (if available), and formats.
    """
    with media_paths_lock:
        if task_id not in media_paths:
            raise HTTPException(
                status_code=404, detail="Task not found or media not registered"
            )
        paths = media_paths[task_id]

    info = {"task_id": task_id, "audio": None, "video": None}

    for media_type in ["audio", "video"]:
        path = paths.get(media_type)
        if path and os.path.exists(path):
            stat = os.stat(path)
            info[media_type] = {
                "path": path,
                "filename": os.path.basename(path),
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "format": os.path.splitext(path)[1][1:].lower(),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }

    return info


@app.get("/api/v1/cache/audio")
async def list_cached_audio(
    current_user: str = Depends(get_current_user_optional),
):
    """
    List all cached audio files with metadata.

    Returns list of {cache_key, source, path, size_mb, format, modified}.
    """
    import audio_cache

    index = audio_cache._load_index()
    results = []

    for cache_key, entry in index["entries"].items():
        path = entry.get("path", "")
        if path and os.path.exists(path):
            stat = os.stat(path)
            ext = os.path.splitext(path)[1][1:].lower()
            results.append(
                {
                    "cache_key": cache_key,
                    "source": entry.get("source", "")[:200],
                    "path": path,
                    "filename": os.path.basename(path),
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "format": ext,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "age_days": round((time.time() - entry.get("mtime", 0)) / 86400, 1),
                }
            )

    return {"cached_audio": sorted(results, key=lambda x: x["modified"], reverse=True)}


@app.delete("/api/v1/cache/audio/{cache_key}")
async def delete_cached_audio(
    cache_key: str,
    current_user: str = Depends(get_current_user),
):
    """
    Delete a cached audio file by cache key.
    """
    import audio_cache

    index = audio_cache._load_index()
    entry = index["entries"].get(cache_key)

    if not entry:
        raise HTTPException(status_code=404, detail="Audio not found in cache")

    path = entry.get("path", "")
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass

    del index["entries"][cache_key]
    audio_cache._save_index(index)

    return {"message": f"Cached audio {cache_key} deleted"}


# =============================================================================
# Mobile App Endpoints (Library / Playback / Connect)
# =============================================================================

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts", ".flv"}
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".ogg", ".opus", ".flac", ".aac", ".webm"}
THUMB_EXTS = {".webp", ".jpg", ".jpeg", ".png"}
SRT_EXTS = {".srt", ".vtt"}


def _safe_output_path(rel_path: str) -> Optional[str]:
    """Resolve a relative path under OUTPUT_DIR, blocking traversal."""
    if not rel_path:
        return None
    base = os.path.abspath(OUTPUT_DIR)
    candidate = os.path.abspath(os.path.join(base, rel_path))
    if not candidate.startswith(base + os.sep) and candidate != base:
        return None
    if not os.path.exists(candidate):
        return None
    return candidate


def _infer_url_from_base(base: str) -> Optional[str]:
    """Extract the source URL from sibling helper files if present."""
    for suffix in [".htm", ".html", ".mpv.json", ".json"]:
        helper = f"{base}{suffix}"
        if not os.path.exists(helper):
            continue
        try:
            if suffix in (".htm", ".html"):
                content = open(helper, encoding="utf-8", errors="ignore").read(2000)
                import re as _re

                m = _re.search(r"URL='([^']+)'", content)
                if m:
                    return m.group(1)
            else:
                data = json.load(open(helper, encoding="utf-8", errors="ignore"))
                url = data.get("url")
                if url:
                    return url
        except Exception:
            continue
    return None


def _library_items() -> List[Dict[str, Any]]:
    """Scan OUTPUT_DIR for subtitle files and their sibling media."""
    items: List[Dict[str, Any]] = []
    if not os.path.isdir(OUTPUT_DIR):
        return items

    for root, _dirs, files in os.walk(OUTPUT_DIR):
        for fname in sorted(files):
            if not fname.endswith(".srt") or ".unfinished" in fname:
                continue
            if os.path.islink(os.path.join(root, fname)):
                continue  # symlink to .unfinished.srt
            srt_path = os.path.join(root, fname)
            base = os.path.splitext(srt_path)[0]
            rel = os.path.relpath(srt_path, OUTPUT_DIR)

            media = []
            thumb = None
            for f in sorted(os.listdir(root)):
                ext = os.path.splitext(f)[1].lower()
                if f.startswith(os.path.basename(base)):
                    full = os.path.join(root, f)
                    if ext in VIDEO_EXTS:
                        media.append({"type": "video", "path": full, "format": ext[1:]})
                    elif ext in AUDIO_EXTS:
                        media.append({"type": "audio", "path": full, "format": ext[1:]})
                    elif ext in THUMB_EXTS and thumb is None:
                        thumb = full

            base_name = os.path.basename(base)
            # Strip model suffix and timestamp prefix for display
            title = base_name
            safe_model_names = [
                m.replace(":", "_") for m in getattr(model, "ALL_MODEL_NAMES", [])
            ]
            for m in sorted(safe_model_names, key=len, reverse=True):
                if title.endswith(f".{m}"):
                    title = title[: -(len(m) + 1)]
                    break
            title = re.sub(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_", "", title)

            items.append(
                {
                    "id": os.path.relpath(srt_path, OUTPUT_DIR).replace(os.sep, "/"),
                    "title": title,
                    "channel": os.path.basename(root),
                    "path": os.path.relpath(srt_path, OUTPUT_DIR).replace(os.sep, "/"),
                    "srt_path": rel.replace(os.sep, "/"),
                    "media": media,
                    "has_video": any(m["type"] == "video" for m in media),
                    "has_audio": any(m["type"] == "audio" for m in media),
                    "has_thumbnail": thumb is not None,
                    "thumbnail_path": (
                        os.path.relpath(thumb, OUTPUT_DIR).replace(os.sep, "/")
                        if thumb
                        else None
                    ),
                    "source_url": _infer_url_from_base(base),
                    "size_bytes": os.path.getsize(srt_path),
                }
            )
    return items


@app.get("/api/v1/library")
async def api_library(
    current_user: str = Depends(get_current_user_optional),
):
    """List all transcribed content on the server (finished SRT files + media)."""
    items = _library_items()
    for it in items:
        rel = it["path"]
        it["urls"] = {
            "srt": f"/api/v1/subs/file?path={rel}",
            "media": [
                {
                    "type": m["type"],
                    "format": m["format"],
                    "url": f"/api/v1/media/file?path={os.path.relpath(m['path'], OUTPUT_DIR).replace(os.sep, '/')}",
                }
                for m in it["media"]
            ],
            "thumbnail": (
                f"/api/v1/thumb/file?path={it['thumbnail_path']}"
                if it["thumbnail_path"]
                else None
            ),
            "play": f"/api/v1/play?source={it['source_url']}&srt={rel}"
            if it["source_url"]
            else None,
        }
    return {"library": items, "count": len(items)}


@app.get("/api/v1/subs/file")
async def api_subtitle_file(
    path: str,
    current_user: str = Depends(get_current_user_optional),
):
    """Serve an SRT/VTT file by relative path."""
    file_path = _safe_output_path(path)
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")
    ext = os.path.splitext(file_path)[1].lower()
    media_type = "text/vtt" if ext == ".vtt" else "text/plain"
    return FileResponse(
        file_path, media_type=media_type, filename=os.path.basename(file_path)
    )


@app.get("/api/v1/media/file")
async def api_media_file(
    path: str,
    range: Optional[str] = Header(None, alias="Range"),
    current_user: str = Depends(get_current_user_optional),
):
    """Stream a local media file (audio/video) by relative path with Range support."""
    file_path = _safe_output_path(path)
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")
    ext = os.path.splitext(file_path)[1].lower()
    if ext in VIDEO_EXTS:
        media_type = {
            ".mp4": "video/mp4",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".m4v": "video/x-m4v",
            ".avi": "video/x-msvideo",
            ".ts": "video/mp2t",
        }.get(ext, "video/mp4")
    elif ext in AUDIO_EXTS:
        media_type = {
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".opus": "audio/opus",
            ".flac": "audio/flac",
            ".aac": "audio/aac",
        }.get(ext, "audio/mpeg")
    else:
        media_type = "application/octet-stream"
    return await _stream_file(file_path, range, media_type, os.path.basename(file_path))


@app.get("/api/v1/thumb/file")
async def api_thumb_file(
    path: str,
    current_user: str = Depends(get_current_user_optional),
):
    """Serve a thumbnail image by relative path."""
    file_path = _safe_output_path(path)
    if not file_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    ext = os.path.splitext(file_path)[1].lower()
    media_type = {
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(ext, "image/jpeg")
    return FileResponse(file_path, media_type=media_type)


@app.get("/api/v1/play")
async def api_play_resolve(
    source: str,
    srt: Optional[str] = None,
    prefer_audio: bool = False,
    current_user: str = Depends(get_current_user_optional),
):
    """
    Resolve playback info for a remote source (yt-dlp/streamlink) plus
    an optional local SRT for sidecar subtitles.
    """
    import api.stream_resolver as stream_resolver

    try:
        info = stream_resolver.resolve_stream(
            source, prefer_audio=prefer_audio, cookies_browser=COOKIES_FROM_BROWSER
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Stream resolution failed: {e}")

    play_url = source
    protocol = info.protocol
    if protocol != "hls":
        # Progressive/direct URLs are IP-bound; proxy through server with Range
        play_url = f"/api/v1/proxy?source={source}"

    payload = info.to_dict()
    payload["play_url"] = play_url
    payload["protocol"] = protocol
    payload["srt_url"] = f"/api/v1/subs/file?path={srt}" if srt else None
    return payload


@app.get("/api/v1/proxy")
async def api_stream_proxy(
    source: str,
    range: Optional[str] = Header(None, alias="Range"),
    current_user: str = Depends(get_current_user_optional),
):
    """
    Proxy a remote stream through the server with Range support.
    Used for IP-bound direct URLs (YouTube googlevideo etc.).
    Falls back to local media if the source matches a local file.
    """
    import api.stream_resolver as stream_resolver

    try:
        info = stream_resolver.resolve_stream(
            source, prefer_audio=False, cookies_browser=COOKIES_FROM_BROWSER
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Stream resolution failed: {e}")

    upstream_url = info.url
    upstream_headers = dict(info.headers or {})

    # Need to peek at status before streaming: use a manual approach
    import httpx

    headers = {"Accept": "*/*"}
    headers.update(upstream_headers)
    if range:
        headers["Range"] = range

    async with httpx.AsyncClient(timeout=60.0) as client:
        req = client.build_request("GET", upstream_url, headers=headers)
        resp = await client.send(req, stream=True)

    if resp.status_code not in (200, 206):
        body = (await resp.aread())[:300]
        raise HTTPException(
            status_code=502,
            detail=f"Upstream returned {resp.status_code}: {body.decode(errors='ignore')}",
        )

    response_headers = {
        "Content-Type": resp.headers.get("Content-Type", "application/octet-stream"),
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    }
    if resp.headers.get("Content-Range"):
        response_headers["Content-Range"] = resp.headers["Content-Range"]
    if resp.headers.get("Content-Length"):
        response_headers["Content-Length"] = resp.headers["Content-Length"]

    async def body_stream():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 64):
                yield chunk
        finally:
            await resp.aclose()

    return StreamingResponse(
        body_stream(),
        status_code=resp.status_code,
        headers=response_headers,
    )


# Cookie browser used for yt-dlp stream resolution (overridable via env)
COOKIES_FROM_BROWSER = os.environ.get("WHISPER_COOKIES_BROWSER", "firefox")


@app.get("/api/v1/live")
async def api_live_tasks(
    current_user: str = Depends(get_current_user_optional),
):
    """List live/active transcription tasks for the Live tab."""
    live = []
    with task_lock:
        for task_id, details in task_status.items():
            status = details.get("status", "")
            if details.get("is_live") or status in (
                "pending",
                "processing",
                "queued",
                "transcribing",
            ):
                entry = {
                    "task_id": task_id,
                    "status": status,
                    "source": details.get("source", ""),
                    "model_name": details.get("model_name", ""),
                    "is_live": bool(details.get("is_live")),
                    "created_at": details.get("created_at", ""),
                    "error": details.get("error"),
                }
                with srt_paths_lock:
                    if task_id in srt_paths:
                        entry["has_subtitles"] = True
                        entry["sse_url"] = f"/api/v1/tasks/{task_id}/subtitles/stream"
                        entry["snapshot_url"] = (
                            f"/api/v1/tasks/{task_id}/subtitles/snapshot"
                        )
                        entry["subs_url"] = f"/api/v1/tasks/{task_id}/subtitles"
                live.append(entry)
    return {"live": live, "count": len(live)}


@app.get("/connect")
async def connect_page():
    """
    Mobile connect page: shows QR code encoding the server URL (and API key if
    present), plus manual entry fields.
    """
    import qrcode
    import qrcode.image.svg

    # Detect server host + port from request
    base_url = f"http://{os.environ.get('WHISPER_HOST', '')}:{os.environ.get('WHISPER_PORT', '8000')}"
    if not os.environ.get("WHISPER_HOST"):
        try:
            import socket

            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            base_url = f"http://{local_ip}:8000"
        except Exception:
            base_url = "http://localhost:8000"

    # Find first valid API key to embed
    api_key = ""
    for user in auth_manager.config.get("users", {}).values():
        keys = user.get("api_keys", [])
        if keys:
            api_key = keys[0]
            break

    connect_data = base_url
    if api_key:
        connect_data = f"{base_url}?api_key={api_key}"

    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(connect_data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    qr_svg = img.to_string().decode("utf-8")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Connect - WhisperSubs Mobile</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #0d1117;
         color: #e6edf3; min-height: 100vh; display: flex; align-items: center;
         justify-content: center; margin: 0; padding: 1rem; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px;
          padding: 2rem; max-width: 420px; width: 100%; text-align: center; }}
  h1 {{ font-size: 1.3rem; margin: 0 0 0.5rem; }}
  p {{ color: #8b949e; font-size: 0.9rem; margin: 0.25rem 0 1.5rem; }}
  .qr {{ background: #fff; padding: 12px; border-radius: 8px; display: inline-block;
        margin-bottom: 1.25rem; max-width: 220px; }}
  .qr svg {{ display: block; width: 100%; height: auto; }}
  .url {{ background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
         padding: 0.6rem 0.8rem; font-family: monospace; font-size: 0.85rem;
         word-break: break-all; margin-bottom: 0.75rem; }}
  .hint {{ font-size: 0.8rem; color: #8b949e; }}
  .key {{ display: inline-block; margin-top: 0.5rem; font-size: 0.75rem;
         color: #58a6ff; word-break: break-all; }}
</style>
</head>
<body>
  <div class="card">
    <h1>WhisperSubs Mobile</h1>
    <p>Scan with the app, or enter the server URL manually.</p>
    <div class="qr">{qr_svg}</div>
    <div class="url">{connect_data}</div>
    <div class="hint">The QR includes the API key for automatic authentication.</div>
    <div class="key">api_key: {api_key or "(none configured)"}</div>
  </div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/live/{task_id}")
async def live_subtitle_page(task_id: str, api_key: Optional[str] = None):
    """
    Mobile-friendly live subtitle viewer page.
    Shows live transcript feed with optional YouTube embed sync.
    """
    # Verify task exists
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="Task not found")

    task = task_status[task_id]
    source = task.get("source", "")

    # Check if source is YouTube for embed mode
    is_youtube = "youtube.com" in source or "youtu.be" in source
    video_id = ""
    if is_youtube:
        import re

        yt_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", source)
        if yt_match:
            video_id = yt_match.group(1)

    # Build base URL for SSE and snapshot endpoints
    # Use relative URLs so it works regardless of host
    sse_url = f"/api/v1/tasks/{task_id}/subtitles/stream"
    snapshot_url = f"/api/v1/tasks/{task_id}/subtitles/snapshot"
    download_url = f"/api/v1/tasks/{task_id}/subtitles"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Subtitles - {task.get("source", "Unknown")}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117; color: #e6edf3;
            min-height: 100vh; display: flex; flex-direction: column;
        }}
        .header {{ 
            background: #161b22; padding: 1rem; border-bottom: 1px solid #30363d;
            display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center;
        }}
        .title {{ font-size: 1.1rem; font-weight: 600; flex: 1; }}
        .badge {{ 
            font-size: 0.7rem; padding: 0.2rem 0.5rem; border-radius: 0.3rem;
            background: #238636; color: white; font-weight: 500;
        }}
        .badge.error {{ background: #da3633; }}
        .badge.warning {{ background: #d29922; }}
        .container {{ flex: 1; display: flex; flex-direction: column; }}
        
        /* YouTube embed mode */
        .video-container {{ 
            position: relative; width: 100%; aspect-ratio: 16/9; background: #000; 
        }}
        .video-container iframe {{ width: 100%; height: 100%; border: none; }}
        .caption-overlay {{ 
            position: absolute; bottom: 5%; left: 5%; right: 5%; 
            background: rgba(0,0,0,0.8); padding: 1rem; border-radius: 0.5rem;
            font-size: 1.2rem; line-height: 1.5; text-align: center;
            color: #fff; text-shadow: 0 0 10px rgba(0,0,0,0.5);
            pointer-events: none; transition: opacity 0.2s;
        }}
        .caption-overlay.hidden {{ opacity: 0; }}
        
        /* Transcript mode */
        .transcript {{ flex: 1; overflow-y: auto; padding: 1rem; }}
        .segment {{ 
            padding: 0.5rem 1rem; margin: 0.25rem 0; 
            border-radius: 0.5rem; background: #161b22;
            border-left: 3px solid #238636; animation: slideIn 0.3s ease;
        }}
        @keyframes slideIn {{ from {{ opacity: 0; transform: translateX(-10px); }} to {{ opacity: 1; transform: translateX(0); }} }}
        .segment.current {{ 
            background: #1f3a5f; border-left-color: #58a6ff; 
            font-weight: 500; font-size: 1.1rem;
        }}
        .segment-time {{ 
            font-size: 0.75rem; color: #8b949e; margin-bottom: 0.25rem;
        }}
        .segment-text {{ font-size: 1rem; line-height: 1.4; }}
        
        .controls {{ 
            padding: 1rem; background: #161b22; border-top: 1px solid #30363d;
            display: flex; gap: 0.5rem; flex-wrap: wrap;
        }}
        .btn {{ 
            padding: 0.5rem 1rem; border: none; border-radius: 0.5rem;
            font-size: 0.9rem; font-weight: 500; cursor: pointer;
            background: #238636; color: white;
        }}
        .btn.secondary {{ background: #21262d; border: 1px solid #30363d; }}
        .btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        .status {{ display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: #8b949e; }}
        .status-dot {{ 
            width: 8px; height: 8px; border-radius: 50%; background: #238636;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .status-dot.ended {{ background: #8b949e; animation: none; }}
        .status-dot.error {{ background: #da3633; }}
        
        .empty-state {{ 
            text-align: center; padding: 3rem 1rem; color: #8b949e;
        }}
        .empty-state svg {{ width: 48px; height: 48px; margin-bottom: 1rem; opacity: 0.5; }}
        
        @media (max-width: 600px) {{
            .title {{ font-size: 1rem; }}
            .segment {{ padding: 0.5rem; }}
            .caption-overlay {{ font-size: 1rem; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="title">Live Subtitles</div>
        <span class="badge" id="statusBadge">Connecting…</span>
    </div>
    
    <div class="container" id="container">
        {
        f'''
        <div class="video-container" id="videoContainer">
            <iframe 
                src="https://www.youtube.com/embed/{video_id}?enablejsapi=1&origin=*" 
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                allowfullscreen
                id="ytPlayer"
            ></iframe>
            <div class="caption-overlay hidden" id="captionOverlay"></div>
        </div>
        '''
        if is_youtube and video_id
        else ""
    }
        
        <div class="transcript" id="transcript" style="{
        "display: none;" if is_youtube and video_id else ""
    }">
            <div class="empty-state" id="emptyState">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
                    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
                </svg>
                <div>Waiting for subtitles…</div>
            </div>
        </div>
    </div>
    
    <div class="controls">
        <div class="status" style="flex: 1;">
            <span class="status-dot" id="statusDot"></span>
            <span id="statusText">Connecting to subtitle stream…</span>
        </div>
        <a class="btn" href="{download_url}" target="_blank" download>Download SRT</a>
        <button class="btn secondary" id="copyBtn" onclick="copyUrl()">Copy SSE URL</button>
    </div>

    <script>
        const taskId = "{task_id}";
        const isYouTube = {str(is_youtube and video_id).lower()};
        const videoId = "{video_id}";
        const sseUrl = "{sse_url}";
        const snapshotUrl = "{snapshot_url}";
        const downloadUrl = "{download_url}";
        
        const transcriptEl = document.getElementById('transcript');
        const emptyState = document.getElementById('emptyState');
        const statusBadge = document.getElementById('statusBadge');
        const statusDot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');
        const copyBtn = document.getElementById('copyBtn');
        const captionOverlay = document.getElementById('captionOverlay');
        let player = null;
        let currentSegmentIndex = -1;
        
        // Initialize YouTube player API if embed mode
        if (isYouTube && videoId) {{
            window.onYouTubeIframeAPIReady = () => {{
                player = new YT.Player('ytPlayer', {{
                    events: {{ 'onReady': onPlayerReady }}
                }});
            }};
        }}
        
        function onPlayerReady(event) {{
            player = event.target;
            // Poll for current time
            setInterval(syncCaption, 200);
        }}
        
        function syncCaption() {{
            if (!player) return;
            const currentTime = player.getCurrentTime();
            const segments = document.querySelectorAll('.segment');
            let activeIndex = -1;
            segments.forEach((seg, idx) => {{
                const start = parseTime(seg.dataset.start);
                const end = parseTime(seg.dataset.end);
                if (currentTime >= start && currentTime <= end) {{
                    activeIndex = idx;
                }}
            }});
            if (activeIndex !== currentSegmentIndex) {{
                segments.forEach(s => s.classList.remove('current'));
                if (activeIndex >= 0) {{
                    segments[activeIndex].classList.add('current');
                    // Update overlay
                    if (captionOverlay) {{
                        captionOverlay.textContent = segments[activeIndex].querySelector('.segment-text').textContent;
                        captionOverlay.classList.remove('hidden');
                    }}
                }} else {{
                    if (captionOverlay) captionOverlay.classList.add('hidden');
                }}
                currentSegmentIndex = activeIndex;
            }}
        }}
        
        function parseTime(str) {{
            const parts = str.split(':');
            return parts.length === 3 
                ? parseInt(parts[0])*3600 + parseInt(parts[1])*60 + parseFloat(parts[2])
                : parseInt(parts[0])*60 + parseFloat(parts[1]);
        }}
        
        // SSE Connection
        const evtSource = new EventSource(sseUrl);
        
        evtSource.addEventListener('segment', (e) => {{
            const data = JSON.parse(e.data);
            statusBadge.textContent = 'Live';
            statusBadge.className = 'badge';
            statusDot.className = 'status-dot';
            statusText.textContent = 'Receiving subtitles…';
            emptyState.style.display = 'none';
            
            const segDiv = document.createElement('div');
            segDiv.className = 'segment';
            segDiv.dataset.start = data.start;
            segDiv.dataset.end = data.end;
            segDiv.innerHTML = `
                <div class="segment-time">${{data.start}} → ${{data.end}}</div>
                <div class="segment-text">${{data.text}}</div>
            `;
            transcriptEl.appendChild(segDiv);
            transcriptEl.scrollTop = transcriptEl.scrollHeight;
        }});
        
        evtSource.addEventListener('done', (e) => {{
            const data = JSON.parse(e.data);
            statusBadge.textContent = 'Completed';
            statusBadge.className = 'badge';
            statusDot.className = 'status-dot ended';
            statusText.textContent = 'Transcription complete';
            evtSource.close();
        }});
        
        evtSource.addEventListener('error', (e) => {{
            if (evtSource.readyState === EventSource.CLOSED) {{
                statusBadge.textContent = 'Disconnected';
                statusBadge.className = 'badge error';
                statusDot.className = 'status-dot error';
                statusText.textContent = 'Connection lost';
            }}
        }});
        
        // Fallback: periodic snapshot polling if SSE fails
        let pollInterval = null;
        function startPolling() {{
            if (pollInterval) return;
            pollInterval = setInterval(async () => {{
                try {{
                    const resp = await fetch(snapshotUrl);
                    if (resp.ok) {{
                        const data = await resp.json();
                        // Could merge new blocks here
                    }}
                }} catch (e) {{}}
            }}, 5000);
        }}
        setTimeout(startPolling, 10000); // Start polling after 10s if SSE fails
        
        // Copy SSE URL
        function copyUrl() {{
            navigator.clipboard.writeText(window.location.origin + sseUrl);
            copyBtn.textContent = 'Copied!';
            setTimeout(() => copyBtn.textContent = 'Copy SSE URL', 2000);
        }}
        
        // Load YouTube API if needed
        if (isYouTube && videoId) {{
            const tag = document.createElement('script');
            tag.src = "https://www.youtube.com/iframe_api";
            document.head.appendChild(tag);
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(html)


@app.post("/api/v1/live")
async def start_live_transcription(
    source: str = Form(...),
    model_name: str = Form("large"),
    device: str = Form("cpu"),
    compute_type: str = Form("int8"),
    force: bool = Form(False),
    language: Optional[str] = Form(None),
    vad_filter: bool = Form(True),
    background_tasks: BackgroundTasks = None,
    current_user: str = Depends(get_current_user),
):
    """
    Start a livestream transcription job.
    Returns task_id for tracking and live subtitle streaming.
    """
    # Validate model
    if model_name not in model.ALL_MODEL_NAMES:
        valid_model_name = model.getName(model_name)
        if not valid_model_name or valid_model_name not in model.ALL_MODEL_NAMES:
            raise HTTPException(status_code=400, detail=f"Invalid model name")
        model_name = valid_model_name

    # Generate task ID
    task_id = f"live_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

    with task_lock:
        task_status[task_id] = {
            "status": "pending",
            "source": source,
            "model_name": model_name,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "progress": None,
            "result": None,
            "error": None,
            "is_live": True,
        }

    # Run livestream transcription in background
    def run_live():
        try:
            with task_lock:
                task_status[task_id]["status"] = "processing"

            # Import here to avoid circular imports
            from livestream_transcriber import start_transcription

            # Use the livestream transcriber
            start_transcription(
                source=source,
                model_name=model_name,
                device=device,
                compute_type=compute_type,
                force=force,
                language=language,
                vad_filter=vad_filter,
                output_dir=OUTPUT_DIR,
                task_id=task_id,  # We'll need to thread this through
            )

            with task_lock:
                task_status[task_id]["status"] = "completed"
                task_status[task_id]["completed_at"] = datetime.now().isoformat()

        except Exception as e:
            with task_lock:
                task_status[task_id]["status"] = "failed"
                task_status[task_id]["error"] = str(e)
                task_status[task_id]["completed_at"] = datetime.now().isoformat()

    background_tasks.add_task(run_live)

    return {
        "task_id": task_id,
        "status": "pending",
        "source": source,
        "model_name": model_name,
        "live_url": f"/live/{task_id}",
        "sse_url": f"/api/v1/tasks/{task_id}/subtitles/stream",
        "snapshot_url": f"/api/v1/tasks/{task_id}/subtitles/snapshot",
        "download_url": f"/api/v1/tasks/{task_id}/subtitles",
    }


def delete_task(task_id: str):
    """Delete a completed/failed task from history"""
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="Task not found")

    if task_status[task_id]["status"] not in ["completed", "failed", "cancelled"]:
        raise HTTPException(
            status_code=400, detail="Can only delete completed/failed tasks"
        )

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
        completed_at=task_status[task_id].get("completed_at"),
    )


@app.get("/tasks", response_model=List[TaskStatusResponse])
def list_tasks():
    """List all tasks"""
    tasks = []
    for task_id, details in task_status.items():
        tasks.append(
            TaskStatusResponse(
                task_id=task_id,
                status=details["status"],
                progress=details.get("progress"),
                result=details.get("result"),
                error=details.get("error"),
                created_at=details["created_at"],
                completed_at=details.get("completed_at"),
            )
        )
    return tasks


@app.get("/jobs", response_model=List[Dict[str, Any]])
def list_jobs():
    """List all transcription jobs"""
    jobs = get_jobs()
    return jobs


@app.get("/health")
def health_check():
    """Health check endpoint with detailed system and task metrics"""
    import psutil

    with resource_lock:
        # Update resource stats
        resource_stats["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        resource_stats["memory_percent"] = psutil.virtual_memory().percent
        resource_stats["disk_usage"] = (
            psutil.disk_usage(OUTPUT_DIR).percent if os.path.exists(OUTPUT_DIR) else 0
        )
        resource_stats["last_update"] = datetime.now().isoformat()

    with task_lock:
        active_tasks = len(
            [t for t in task_status.values() if t["status"] == "processing"]
        )
        queued_tasks = len([t for t in task_status.values() if t["status"] == "queued"])

    with batch_lock:
        active_batches = len(
            [b for b in batch_status.values() if b.get("completed_at") is None]
        )

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "resources": resource_stats.copy(),
        "tasks": {
            "total": len(task_status),
            "active": active_tasks,
            "queued": queued_tasks,
        },
        "batches": {"total": len(batch_status), "active": active_batches},
        "executor": {
            "max_workers": executor.max_workers,
            "active_tasks": executor.get_active_count(),
        },
    }


@app.get("/metrics")
def get_metrics():
    """Get detailed system and performance metrics"""
    import psutil

    # CPU info
    cpu_info = {
        "percent": psutil.cpu_percent(interval=0.1),
        "count_physical": psutil.cpu_count(logical=False),
        "count_logical": psutil.cpu_count(logical=True),
        "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
    }

    # Memory info
    mem = psutil.virtual_memory()
    memory_info = {
        "total_gb": mem.total / (1024**3),
        "available_gb": mem.available / (1024**3),
        "percent": mem.percent,
        "used_gb": mem.used / (1024**3),
    }

    # Disk info
    disk = psutil.disk_usage(OUTPUT_DIR) if os.path.exists(OUTPUT_DIR) else None
    disk_info = (
        {
            "total_gb": disk.total / (1024**3) if disk else 0,
            "used_gb": disk.used / (1024**3) if disk else 0,
            "free_gb": disk.free / (1024**3) if disk else 0,
            "percent": disk.percent if disk else 0,
        }
        if disk
        else {"error": "Output directory not found"}
    )

    # Task statistics
    with task_lock:
        task_stats = {"total": len(task_status), "by_status": {}}
        for task in task_status.values():
            status = task.get("status", "unknown")
            task_stats["by_status"][status] = task_stats["by_status"].get(status, 0) + 1

    # Batch statistics
    with batch_lock:
        batch_stats = {
            "total": len(batch_status),
            "total_tasks": sum(b["total"] for b in batch_status.values()),
            "completed_tasks": sum(
                b.get("completed", 0) for b in batch_status.values()
            ),
        }

    return {
        "timestamp": datetime.now().isoformat(),
        "cpu": cpu_info,
        "memory": memory_info,
        "disk": disk_info,
        "tasks": task_stats,
        "batches": batch_stats,
        "executor": {
            "max_workers": executor.max_workers,
            "active": executor.get_active_count(),
        },
    }


if __name__ == "__main__":
    import uvicorn

    # Use socket_app instead of app for Socket.IO support
    uvicorn.run(socket_app, host="0.0.0.0", port=8000)
