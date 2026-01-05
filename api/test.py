#!/usr/bin/env python3
"""
Test script to verify that the WhisperSubs API can be imported and used
"""
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from api.server import app
    print("✓ Successfully imported API server")
    
    from api.main import main
    print("✓ Successfully imported API main")
    
    print("\nAPI server is ready to run!")
    print("To start the server, run: python -m api.main")
    
except ImportError as e:
    print(f"✗ Error importing API: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)