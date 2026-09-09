#!/usr/bin/env python3
"""
Async SRT file tailer for real-time subtitle streaming.

Watches a growing .unfinished.srt file, parses complete SRT blocks,
and yields them as they're written. Handles partial blocks, file
rotation (rename .unfinished.srt -> .srt), and cleanup.
"""

import asyncio
import os
import re
from pathlib import Path
from typing import AsyncIterator, Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass


@dataclass
class SRTBlock:
    """Parsed SRT subtitle block."""

    index: int
    start: str
    end: str
    text: str
    raw: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }


class SRTTailer:
    """
    Tails an SRT file and yields complete blocks as they're flushed.

    Handles:
    - Partial blocks (buffers until complete)
    - File rotation (unfinished.srt -> .srt rename)
    - Efficient seeking (only reads new data)
    """

    SRT_BLOCK_PATTERN = re.compile(
        r"^(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+?)\n\n",
        re.MULTILINE | re.DOTALL,
    )

    def __init__(
        self,
        file_path: str,
        poll_interval: float = 0.25,
        on_rename: Optional[Callable[[str], None]] = None,
    ):
        self.file_path = Path(file_path).resolve()
        self.poll_interval = poll_interval
        self.on_rename = on_rename
        self._buffer = ""
        self._position = 0
        self._finished = False
        self._rename_detected = False

    async def tail(self) -> AsyncIterator[SRTBlock]:
        """
        Async generator that yields complete SRT blocks as they're written.

        Yields:
            SRTBlock: Parsed subtitle blocks

        Raises:
            FileNotFoundError: If the file doesn't exist initially
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"SRT file not found: {self.file_path}")

        # Initial position at end of existing content
        self._position = self.file_path.stat().st_size

        while not self._finished:
            await asyncio.sleep(self.poll_interval)

            try:
                await self._check_rename()

                if self._rename_detected:
                    self._finished = True
                    break

                blocks = await self._read_new_blocks()
                for block in blocks:
                    yield block

            except (OSError, IOError) as e:
                # File might be temporarily unavailable
                await asyncio.sleep(self.poll_interval)
                continue

    async def _check_rename(self) -> None:
        """Check if .unfinished.srt was renamed to .srt."""
        if self._rename_detected:
            return

        # If our file path was .unfinished.srt and it's gone, check for .srt
        if self.file_path.suffix == ".srt" and ".unfinished" in self.file_path.stem:
            base_name = self.file_path.stem.replace(".unfinished", "")
            final_path = self.file_path.with_stem(base_name)
            if final_path.exists() and not self.file_path.exists():
                self._rename_detected = True
                if self.on_rename:
                    self.on_rename(str(final_path))

    async def _read_new_blocks(self) -> list[SRTBlock]:
        """Read new content from file and parse complete SRT blocks."""
        if not self.file_path.exists():
            return []

        try:
            stat = self.file_path.stat()
            current_size = stat.st_size

            if current_size < self._position:
                # File was truncated or rotated
                self._position = 0
                self._buffer = ""

            if current_size == self._position:
                return []

            # Read only new data
            with open(self.file_path, "r", encoding="utf-8") as f:
                f.seek(self._position)
                new_data = f.read(current_size - self._position)

            self._position = current_size
            self._buffer += new_data

            # Parse complete blocks (ending with double newline)
            blocks = []
            while True:
                match = self.SRT_BLOCK_PATTERN.search(self._buffer)
                if not match:
                    break

                start, end = match.span()
                block = SRTBlock(
                    index=int(match.group(1)),
                    start=match.group(2),
                    end=match.group(3),
                    text=match.group(4).strip(),
                    raw=match.group(0),
                )
                blocks.append(block)

                # Remove parsed block from buffer
                self._buffer = self._buffer[end:]

            return blocks

        except (OSError, IOError):
            return []

    def get_snapshot(self) -> list[SRTBlock]:
        """Get all currently available blocks (for snapshot endpoint)."""
        # Read entire file
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, IOError, FileNotFoundError):
            return []

        blocks = []
        for match in self.SRT_BLOCK_PATTERN.finditer(content):
            blocks.append(
                SRTBlock(
                    index=int(match.group(1)),
                    start=match.group(2),
                    end=match.group(3),
                    text=match.group(4).strip(),
                    raw=match.group(0),
                )
            )
        return blocks

    def stop(self) -> None:
        """Stop the tailer."""
        self._finished = True


class SRTTailerManager:
    """
    Manages multiple SRTTailer instances for different tasks.
    """

    def __init__(self):
        self._tailers: Dict[str, SRTTailer] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    async def start_tailing(
        self,
        task_id: str,
        file_path: str,
        on_segment: Callable[[str, SRTBlock], Awaitable[None]],
        on_done: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> bool:
        """Start tailing a file for a task."""
        if task_id in self._tailers:
            return False

        if not Path(file_path).exists():
            return False

        async def run_tailer():
            def handle_rename(path):
                if on_done:
                    asyncio.create_task(on_done(task_id))

            tailer = SRTTailer(file_path, on_rename=handle_rename)
            self._tailers[task_id] = tailer

            try:
                async for block in tailer.tail():
                    if on_segment:
                        await on_segment(task_id, block)
            except FileNotFoundError:
                pass
            finally:
                self._tailers.pop(task_id, None)

        self._tasks[task_id] = asyncio.create_task(run_tailer())
        return True

    def stop_tailing(self, task_id: str) -> None:
        """Stop tailing for a task."""
        tailer = self._tailers.pop(task_id, None)
        if tailer:
            tailer.stop()
        task = self._tasks.pop(task_id, None)
        if task:
            task.cancel()

    def get_tailer(self, task_id: str) -> Optional[SRTTailer]:
        """Get the tailer for a task."""
        return self._tailers.get(task_id)

    async def stop_all(self) -> None:
        """Stop all tailers."""
        for task_id in list(self._tailers.keys()):
            self.stop_tailing(task_id)
        # Wait for tasks to finish
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()


# Convenience function for simple use cases
async def tail_srt_file(file_path: str) -> AsyncIterator[SRTBlock]:
    """Simple async iterator for tailing a single SRT file."""
    tailer = SRTTailer(file_path)
    try:
        async for block in tailer.tail():
            yield block
    except FileNotFoundError:
        return
