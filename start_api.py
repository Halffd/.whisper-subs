#!/usr/bin/env python3
"""
WhisperSubs API Server - Startup Script

This script provides a simple way to start the FastAPI server.
"""
import os
import sys
from pathlib import Path

def main():
    print("WhisperSubs API Server")
    print("=====================")
    
    # Check if required packages are available
    try:
        import fastapi
        import uvicorn
        import pydantic
        print("✓ Required packages are available")
    except ImportError as e:
        print(f"✗ Missing required package: {e}")
        print("\nPlease install the required packages:")
        print("pip install fastapi uvicorn[standard] pydantic")
        sys.exit(1)
    
    # Add the project root to the Python path
    project_root = Path(__file__).parent
    sys.path.insert(0, str(project_root))
    
    print(f"Project root: {project_root}")
    
    # Check if whisper_subs is available
    try:
        from whisper_subs import WhisperSubs
        print("✓ WhisperSubs module is available")
    except ImportError as e:
        print(f"✗ Error importing WhisperSubs: {e}")
        sys.exit(1)
    
    # Import and run the API server
    try:
        from api.server import app
        
        # Get command-line arguments or use defaults
        host = "0.0.0.0"
        port = 8000
        reload = False
        
        if len(sys.argv) > 1:
            for i, arg in enumerate(sys.argv):
                if arg == "--host" and i + 1 < len(sys.argv):
                    host = sys.argv[i + 1]
                elif arg == "--port" and i + 1 < len(sys.argv):
                    port = int(sys.argv[i + 1])
                elif arg == "--reload":
                    reload = True
        
        print(f"Starting API server on {host}:{port}")
        print(f"API Documentation available at: http://{host}:{port}/docs")
        
        uvicorn.run(app, host=host, port=port, reload=reload, log_level="info")
        
    except Exception as e:
        print(f"✗ Error starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()