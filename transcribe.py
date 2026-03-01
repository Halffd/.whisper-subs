"""
Backward compatibility wrapper - imports from unified transcription module.
This file is kept for legacy imports but all functionality is in transcribe_unified.py
"""

# Import everything from unified module for backward compatibility
from transcribe_unified import (
    Segment,
    format_timestamp,
    srt_time_to_seconds,
    get_srt_resume_info,
    filter_garbage_segments,
    merge_adjacent_identical_segments,
    transcribe_audio,
    transcribe_with_resume,
    process_create,
    make_files
)

# Re-export commonly used functions
__all__ = [
    'Segment',
    'format_timestamp', 
    'srt_time_to_seconds',
    'get_srt_resume_info',
    'filter_garbage_segments',
    'merge_adjacent_identical_segments',
    'transcribe_audio',
    'transcribe_with_resume',
    'process_create',
    'make_files'
]
