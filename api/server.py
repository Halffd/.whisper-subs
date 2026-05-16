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
from typing import Optional, List, Dict, Any, Callable
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, WebSocket, WebSocketDisconnect, Depends, Security, Form
from fastapi.security import APIKeyHeader, APIKeyQuery
from fastapi.responses import JSONResponse, FileResponse
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

# Configuration
API_CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'api_config.json')
JWT_SECRET_KEY = os.environ.get('WHISPER_JWT_SECRET', secrets.token_urlsafe(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Authentication schemes
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
API_KEY_QUERY = APIKeyQuery(name="api_key", auto_error=False)

# Create the FastAPI app
app = FastAPI(
    title="WhisperSubs API",
    description="API for transcribing audio from various sources using Whisper",
    version="3.0.0"
)

# Authentication Manager
class AuthManager:
    """Manage API keys, users, and JWT tokens"""
    
    def __init__(self, config_file: str):
        self.config_file = config_file
        self.config = self._load_config()
        self.token_blacklist: set = set()
        self.lock = threading.Lock()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load or create API configuration"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        
        # Default configuration
        config: Dict[str, Any] = {
            "users": {
                "admin": {
                    "password_hash": bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode(),
                    "api_keys": [secrets.token_urlsafe(32)],
                    "role": "admin",
                    "created_at": datetime.now().isoformat()
                }
            },
            "settings": {
                "require_auth": True,
                "allow_registration": False,
                "max_tasks_per_user": 10,
                "rate_limit_per_minute": 60
            }
        }
        
        self._save_config(config)
        return config
    
    def _save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration to file"""
        with self.lock:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
    
    def verify_password(self, username: str, password: str) -> bool:
        """Verify user password"""
        if username not in self.config.get('users', {}):
            return False
        user = self.config['users'][username]
        return bcrypt.checkpw(password.encode(), user['password_hash'].encode())
    
    def create_api_key(self, username: str) -> Optional[str]:
        """Generate new API key for user"""
        if username not in self.config.get('users', {}):
            return None
        
        api_key = secrets.token_urlsafe(32)
        self.config['users'][username]['api_keys'].append(api_key)
        self._save_config(self.config)
        return api_key
    
    def verify_api_key(self, api_key: str) -> Optional[str]:
        """Verify API key and return username if valid"""
        for username, user_data in self.config.get('users', {}).items():
            if api_key in user_data.get('api_keys', []):
                return username
        return None
    
    def create_jwt_token(self, username: str, expires_hours: Optional[int] = None) -> str:
        """Create JWT token for user"""
        if expires_hours is None:
            expires_hours = JWT_EXPIRATION_HOURS
        
        payload = {
            "sub": username,
            "exp": datetime.now() + timedelta(hours=expires_hours),
            "iat": datetime.now(),
            "type": "access"
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
        if username not in self.config.get('users', {}):
            return None
        
        user = self.config['users'][username]
        return {
            "username": username,
            "role": user.get('role', 'user'),
            "created_at": user.get('created_at'),
            "api_keys_count": len(user.get('api_keys', []))
        }
    
    def register_user(self, username: str, password: str) -> bool:
        """Register new user"""
        if not self.config.get('settings', {}).get('allow_registration', False):
            return False
        
        if username in self.config.get('users', {}):
            return False
        
        self.config['users'][username] = {
            "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            "api_keys": [secrets.token_urlsafe(32)],
            "role": "user",
            "created_at": datetime.now().isoformat()
        }
        self._save_config(self.config)
        return True
    
    def delete_api_key(self, username: str, api_key: str) -> bool:
        """Delete specific API key"""
        if username not in self.config.get('users', {}):
            return False
        
        keys = self.config['users'][username]['api_keys']
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
    authorization: Optional[str] = None
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
    
    raise HTTPException(status_code=401, detail="Invalid or missing authentication credentials")


async def get_current_user_optional(
    api_key_header: Optional[str] = Security(API_KEY_HEADER),
    api_key_query: Optional[str] = Security(API_KEY_QUERY)
) -> Optional[str]:
    """Get current user if authenticated, None otherwise"""
    api_key = api_key_header or api_key_query
    if api_key:
        return auth_manager.verify_api_key(api_key)
    return None

# Socket.IO server for real-time progress updates
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
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
                    'priority': priority,
                    'started_at': datetime.now(),
                    'status': 'queued'
                }
        
        def wrapper():
            if task_id:
                with self.task_lock:
                    self.active_tasks[task_id]['status'] = 'running'
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
            return len([t for t in self.active_tasks.values() if t['status'] == 'running'])
    
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
    'cpu_percent': 0,
    'memory_percent': 0,
    'disk_usage': 0,
    'last_update': datetime.now()
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
    concurrent: int = Field(3, ge=1, le=8, description="Number of concurrent transcriptions")
    priority: int = Field(5, ge=1, le=10, description="Batch priority")
    auto_retry_failed: bool = Field(True, description="Automatically retry failed tasks with smaller models")


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
    authorization: Optional[str] = None,
    current_user: str = Depends(get_current_user)
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
    return {"api_key": api_key, "message": "Store this key securely - it won't be shown again"}


@app.get("/auth/api-keys")
async def list_api_keys(current_user: str = Depends(get_current_user)):
    """List API keys for current user (masked)"""
    user = auth_manager.config['users'].get(current_user, {})
    keys = user.get('api_keys', [])
    # Mask all but first 8 and last 8 characters
    masked_keys = [f"{k[:8]}...{k[-8:]}" if len(k) > 16 else "***" for k in keys]
    return {"api_keys": masked_keys, "count": len(keys)}


@app.delete("/auth/api-keys/{api_key}")
async def delete_api_key(
    api_key: str,
    current_user: str = Depends(get_current_user)
):
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
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    
    if not auth_manager.register_user(username, password):
        raise HTTPException(status_code=400, detail="Registration failed or username already exists")
    
    # Auto-login after registration
    token = auth_manager.create_jwt_token(username)
    user_info = auth_manager.get_user_info(username)
    
    return {
        "message": "User registered successfully",
        "access_token": token,
        "user": user_info
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
    current_user: str = Depends(get_current_user)
):
    """Start a new transcription task with advanced options"""
    # Validate model name
    if request.model_name not in model.ALL_MODEL_NAMES:
        valid_model_name = model.getName(request.model_name)
        if not valid_model_name or valid_model_name not in model.ALL_MODEL_NAMES:
            raise HTTPException(status_code=400, detail=f"Invalid model name. Valid models: {model.ALL_MODEL_NAMES}")
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
async def start_batch_transcription(
    request: BatchTranscriptionRequest,
    background_tasks: BackgroundTasks,
    current_user: str = Depends(get_current_user)
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
                    if task_status.get(task_id, {}).get('status') == 'cancelled':
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
                    idx  # Pass index for retry logic
                )
        
        # Create tasks for all sources
        tasks = [
            process_single_task(idx, source)
            for idx, source in sorted_sources
        ]
        
        # Run all tasks with concurrency limit and exception handling
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any exceptions that weren't caught
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                task_id = task_ids[idx]
                with task_lock:
                    if task_id in task_status:
                        task_status[task_id]['status'] = 'failed'
                        task_status[task_id]['error'] = str(result)
                        task_status[task_id]['completed_at'] = datetime.now().isoformat()
                        batch_status[batch_id]['failed'] += 1
                        batch_status[batch_id]['processing'] = max(0, batch_status[batch_id]['processing'] - 1)
                print(f"Task {task_id} failed with exception: {result}")
        
        # Update batch status when all tasks complete
        with batch_lock:
            batch_status[batch_id]['completed_at'] = datetime.now().isoformat()
            # Recalculate counts from tasks
            completed = sum(1 for tid in task_ids if task_status.get(tid, {}).get('status') == 'completed')
            failed = sum(1 for tid in task_ids if task_status.get(tid, {}).get('status') == 'failed')
            batch_status[batch_id]['completed'] = completed
            batch_status[batch_id]['failed'] = failed
            batch_status[batch_id]['pending'] = 0
            batch_status[batch_id]['processing'] = 0
        
        # Emit batch completion
        await sio.emit('batch_completed', {
            'batch_id': batch_id,
            'total': len(task_ids),
            'completed': batch_status[batch_id]['completed'],
            'failed': batch_status[batch_id]['failed']
        })
    
    def run_single_transcription(task_id: str, source: str, request: BatchTranscriptionRequest, batch_id: str, task_index: int):
        """Run single transcription within batch with retry support"""
        max_retries = 3 if request.auto_retry_failed else 1
        models_to_try = [request.model_name]
        
        # Add fallback models if retry is enabled
        if request.retry:
            fallback_models = ['medium', 'small', 'base']
            models_to_try.extend([m for m in fallback_models if m != request.model_name])
        
        for attempt, model_name in enumerate(models_to_try[:max_retries]):
            try:
                with task_lock:
                    if attempt == 0:
                        task_status[task_id]['status'] = 'processing'
                        batch_status[batch_id]['processing'] += 1
                        batch_status[batch_id]['pending'] -= 1
                    else:
                        task_status[task_id]['progress'] = f"Retry {attempt}/{max_retries} with {model_name}"
                
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
                    mpv_socket=request.mpv_socket
                )
                
                job = add_job(source, model_name)
                processor.process(source)
                
                with task_lock:
                    task_status[task_id]['status'] = 'completed'
                    task_status[task_id]['completed_at'] = datetime.now().isoformat()
                    task_status[task_id]['model_name'] = model_name
                    batch_status[batch_id]['completed'] += 1
                    batch_status[batch_id]['processing'] -= 1
                
                # Success - break retry loop
                break
                
            except Exception as e:
                is_last_attempt = attempt >= len(models_to_try) - 1 or attempt >= max_retries - 1
                
                if is_last_attempt:
                    with task_lock:
                        task_status[task_id]['status'] = 'failed'
                        task_status[task_id]['error'] = str(e)
                        task_status[task_id]['completed_at'] = datetime.now().isoformat()
                        batch_status[batch_id]['failed'] += 1
                        if batch_status[batch_id]['processing'] > 0:
                            batch_status[batch_id]['processing'] -= 1
                    print(f"Task {task_id} failed after {attempt + 1} attempts: {e}")
                else:
                    print(f"Task {task_id} attempt {attempt + 1} failed, retrying with {models_to_try[attempt + 1]}...")
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
    """Health check endpoint with detailed system and task metrics"""
    import psutil
    
    with resource_lock:
        # Update resource stats
        resource_stats['cpu_percent'] = psutil.cpu_percent(interval=0.1)
        resource_stats['memory_percent'] = psutil.virtual_memory().percent
        resource_stats['disk_usage'] = psutil.disk_usage(OUTPUT_DIR).percent if os.path.exists(OUTPUT_DIR) else 0
        resource_stats['last_update'] = datetime.now().isoformat()
    
    with task_lock:
        active_tasks = len([t for t in task_status.values() if t["status"] == "processing"])
        queued_tasks = len([t for t in task_status.values() if t["status"] == "queued"])
    
    with batch_lock:
        active_batches = len([b for b in batch_status.values() if b.get('completed_at') is None])
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "resources": resource_stats.copy(),
        "tasks": {
            "total": len(task_status),
            "active": active_tasks,
            "queued": queued_tasks
        },
        "batches": {
            "total": len(batch_status),
            "active": active_batches
        },
        "executor": {
            "max_workers": executor.max_workers,
            "active_tasks": executor.get_active_count()
        }
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
        "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None
    }
    
    # Memory info
    mem = psutil.virtual_memory()
    memory_info = {
        "total_gb": mem.total / (1024**3),
        "available_gb": mem.available / (1024**3),
        "percent": mem.percent,
        "used_gb": mem.used / (1024**3)
    }
    
    # Disk info
    disk = psutil.disk_usage(OUTPUT_DIR) if os.path.exists(OUTPUT_DIR) else None
    disk_info = {
        "total_gb": disk.total / (1024**3) if disk else 0,
        "used_gb": disk.used / (1024**3) if disk else 0,
        "free_gb": disk.free / (1024**3) if disk else 0,
        "percent": disk.percent if disk else 0
    } if disk else {"error": "Output directory not found"}
    
    # Task statistics
    with task_lock:
        task_stats = {
            "total": len(task_status),
            "by_status": {}
        }
        for task in task_status.values():
            status = task.get('status', 'unknown')
            task_stats['by_status'][status] = task_stats['by_status'].get(status, 0) + 1
    
    # Batch statistics
    with batch_lock:
        batch_stats = {
            "total": len(batch_status),
            "total_tasks": sum(b['total'] for b in batch_status.values()),
            "completed_tasks": sum(b.get('completed', 0) for b in batch_status.values())
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
            "active": executor.get_active_count()
        }
    }


if __name__ == "__main__":
    import uvicorn
    # Use socket_app instead of app for Socket.IO support
    uvicorn.run(socket_app, host="0.0.0.0", port=8000)