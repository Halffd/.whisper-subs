#!/usr/bin/env python3
"""
Tests for srt_tailer.py
"""

import asyncio
import tempfile
import os
import pytest
from srt_tailer import SRTTailer, SRTTailerManager, SRTBlock


class TestSRTBlock:
    def test_to_dict(self):
        block = SRTBlock(
            index=1,
            start="00:00:01,000",
            end="00:00:04,000",
            text="Hello world",
            raw="1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n",
        )
        d = block.to_dict()
        assert d["index"] == 1
        assert d["start"] == "00:00:01,000"
        assert d["end"] == "00:00:04,000"
        assert d["text"] == "Hello world"


class TestSRTTailer:
    def test_snapshot_existing_file(self):
        test_srt = """1
00:00:01,000 --> 00:00:04,000
Hello world

2
00:00:05,000 --> 00:00:08,000
This is a test

"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as f:
            f.write(test_srt)
            test_path = f.name

        try:
            tailer = SRTTailer(test_path)
            blocks = tailer.get_snapshot()
            assert len(blocks) == 2
            assert blocks[0].index == 1
            assert blocks[0].text == "Hello world"
            assert blocks[1].index == 2
            assert blocks[1].text == "This is a test"
        finally:
            os.unlink(test_path)

    def test_snapshot_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as f:
            test_path = f.name

        try:
            tailer = SRTTailer(test_path)
            blocks = tailer.get_snapshot()
            assert len(blocks) == 0
        finally:
            os.unlink(test_path)

    def test_snapshot_missing_file(self):
        tailer = SRTTailer("/nonexistent/path.srt")
        blocks = tailer.get_snapshot()
        assert len(blocks) == 0

    @pytest.mark.asyncio
    async def test_tail_live_appending(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".unfinished.srt", delete=False
        ) as f:
            test_path = f.name

        try:
            tailer = SRTTailer(test_path)
            received = []

            async def collect_blocks():
                async for block in tailer.tail():
                    received.append(block)
                    if len(received) >= 3:
                        tailer.stop()

            # Start tailing in background
            task = asyncio.create_task(collect_blocks())
            await asyncio.sleep(0.2)

            # Append blocks
            blocks_to_write = [
                "1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n",
                "2\n00:00:05,000 --> 00:00:08,000\nThis is a test\n\n",
                "3\n00:00:09,000 --> 00:00:12,000\nStreaming subtitles\n\n",
            ]

            for block in blocks_to_write:
                with open(test_path, "a") as f:
                    f.write(block)
                    f.flush()
                await asyncio.sleep(0.2)

            await asyncio.wait_for(task, timeout=2.0)

            assert len(received) == 3
            assert received[0].text == "Hello world"
            assert received[1].text == "This is a test"
            assert received[2].text == "Streaming subtitles"
        finally:
            os.unlink(test_path)

    @pytest.mark.asyncio
    async def test_tail_rename_detection(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".unfinished.srt", delete=False
        ) as f:
            test_path = f.name

        try:
            tailer = SRTTailer(test_path)
            done_called = []

            def on_rename(path):
                done_called.append(path)

            tailer.on_rename = on_rename

            async def collect():
                async for block in tailer.tail():
                    pass  # Just consume

            task = asyncio.create_task(collect())
            await asyncio.sleep(0.2)

            # Write a block
            with open(test_path, "a") as f:
                f.write("1\n00:00:01,000 --> 00:00:04,000\nHello\n\n")
                f.flush()
            await asyncio.sleep(0.2)

            # Rename
            final_path = test_path.replace(".unfinished.srt", ".srt")
            os.rename(test_path, final_path)
            await asyncio.sleep(0.3)

            # Should have detected rename
            assert len(done_called) == 1
            assert done_called[0] == final_path

            # Give tailer time to finish
            await asyncio.sleep(0.2)
        finally:
            if os.path.exists(final_path):
                os.unlink(final_path)


class TestSRTTailerManager:
    @pytest.mark.asyncio
    async def test_start_stop_tailing(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".unfinished.srt", delete=False
        ) as f:
            test_path = f.name

        try:
            manager = SRTTailerManager()
            received = []
            done = []

            async def on_seg(tid, block):
                received.append(block)

            async def on_done(tid):
                done.append(tid)

            await manager.start_tailing("test1", test_path, on_seg, on_done)
            await asyncio.sleep(0.2)

            # Append blocks
            blocks_to_write = [
                "1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n",
                "2\n00:00:05,000 --> 00:00:08,000\nThis is a test\n\n",
            ]

            for block in blocks_to_write:
                with open(test_path, "a") as f:
                    f.write(block)
                    f.flush()
                await asyncio.sleep(0.2)

            # Rename to test done
            final_path = test_path.replace(".unfinished.srt", ".srt")
            os.rename(test_path, final_path)
            await asyncio.sleep(0.3)

            manager.stop_tailing("test1")

            assert len(received) == 2
            assert len(done) == 1
            assert done[0] == "test1"
        finally:
            if os.path.exists(final_path):
                os.unlink(final_path)

    @pytest.mark.asyncio
    async def test_snapshot_via_manager(self):
        test_srt = """1
00:00:01,000 --> 00:00:04,000
Hello world

"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as f:
            f.write(test_srt)
            test_path = f.name

        try:
            manager = SRTTailerManager()
            await manager.start_tailing("test1", test_path, lambda *a: None)
            await asyncio.sleep(0.2)

            tailer = manager.get_tailer("test1")
            assert tailer is not None
            blocks = tailer.get_snapshot()
            assert len(blocks) == 1
            assert blocks[0].text == "Hello world"

            manager.stop_tailing("test1")
        finally:
            os.unlink(test_path)

    @pytest.mark.asyncio
    async def test_stop_all(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".unfinished.srt", delete=False
        ) as f:
            test_path = f.name

        try:
            manager = SRTTailerManager()
            await manager.start_tailing("test1", test_path, lambda *a: None)
            await manager.start_tailing("test2", test_path, lambda *a: None)
            await asyncio.sleep(0.2)

            await manager.stop_all()
            await asyncio.sleep(0.1)

            assert len(manager._tailers) == 0
            assert len(manager._tasks) == 0
        finally:
            os.unlink(test_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
