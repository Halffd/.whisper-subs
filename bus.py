#!/usr/bin/env python3
"""
Bridge: Takes SRT output from your transcriber and feeds it to D-Bus
So your viewer can display it in real-time
"""

import time
import os
from pydbus import SessionBus
from gi.repository import GLib

class SRTToDBusBridge:
    def __init__(self, srt_file):
        self.srt_file = srt_file
        self.last_position = 0
        self.bus = SessionBus()
        
    def watch_and_broadcast(self):
        """Watch SRT file and broadcast new lines to D-Bus"""
        print(f"Watching {self.srt_file} for changes...")
        
        while True:
            if os.path.exists(self.srt_file):
                current_size = os.path.getsize(self.srt_file)
                
                if current_size > self.last_position:
                    with open(self.srt_file, 'r', encoding='utf-8') as f:
                        f.seek(self.last_position)
                        new_content = f.read()
                        
                        # Extract just the text (ignore timestamps and numbers)
                        lines = new_content.split('\n')
                        text_lines = [l for l in lines if l.strip() and 
                                     not l.strip().isdigit() and 
                                     '-->' not in l]
                        
                        for line in text_lines:
                            if line.strip():
                                # Broadcast to D-Bus (mimicking LiveCaptions)
                                try:
                                    # You'd need to implement a D-Bus service here
                                    # Or just print for now
                                    print(f"Broadcasting: {line.strip()}")
                                except Exception as e:
                                    print(f"Error broadcasting: {e}")
                        
                        self.last_position = current_size
            
            time.sleep(0.1)  # Check every 100ms

if __name__ == "__main__":
    import sys
    srt_file = sys.argv[1] if len(sys.argv) > 1 else "output.srt"
    bridge = SRTToDBusBridge(srt_file)
    bridge.watch_and_broadcast()