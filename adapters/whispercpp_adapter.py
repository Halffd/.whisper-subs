"""WhisperCppAdapter - whisper.cpp CLI transcription.

Runs whisper-cli (or the classic main binary) as a subprocess and parses
the SRT it writes to disk. The CLI prints its transcript to stdout only
in the default text mode; -osrt writes <output-file>.srt (cli.cpp
fout_factory), so the adapter pins the name with -of and reads that file
rather than stdout.

whisper-cli writes that file only after the whole input has been decoded,
so one run over a full episode means an hour (on a weak CPU, a day) of
silence - and when the run is killed, a subtitle file without a single
cue in it. This adapter therefore works in chunks: the audio is cut into
pieces, every piece is transcribed in its own whisper-cli run (-pp makes
the CLI report its progress, which is echoed here), and the cues of a
finished piece are handed to the caller right away, so the growing
``.unfinished`` subtitle shows real progress. Chunks that are already
transcribed are kept in a cache directory, so an interrupted run resumes
instead of starting over.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from typing import Any, Callable, Iterator, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


class WhisperCppStopped(Exception):
    """Raised when the caller asked for the transcription to stop."""


class WhisperCppTimeout(RuntimeError):
    """A single whisper-cli run exceeded its wall-clock limit."""


def _hms(seconds: float) -> str:
    """Format a duration as MM:SS (H:MM:SS beyond an hour) for progress lines."""
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class SegmentStream:
    """Lazy list of segments that can also be consumed as an iterator.

    A streaming adapter cannot return a finished list: the cues arrive
    while the model is still running. Existing callers (and the test
    suite) treat the return value as a sequence, so this object plays
    both parts: iterating pulls one segment at a time out of the source
    iterator, while ``len()`` and indexing materialise what is still
    missing and then behave like a list.
    """

    _END = object()

    def __init__(self, source: Iterator[Segment]):
        self._source = iter(source)
        self._buffer: List[Segment] = []
        self._done = False

    def __iter__(self):
        index = 0
        while True:
            if index < len(self._buffer):
                yield self._buffer[index]
                index += 1
                continue
            item = self._next()
            if item is self._END:
                return
            yield item
            index += 1

    def __len__(self) -> int:
        self._materialize()
        return len(self._buffer)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self)[index]
        if index < 0:
            self._materialize()
            return self._buffer[index]
        while len(self._buffer) <= index:
            if self._next() is self._END:
                raise IndexError("segment index out of range")
        return self._buffer[index]

    def __bool__(self) -> bool:
        # Never materialise: "if segments:" must not start the model.
        return True

    def _next(self):
        """Pull one segment off the source, buffering it.

        Returns ``_END`` when the source is exhausted. Every pulled
        segment is buffered, so a second pass (indexing, a list()) sees
        the same cues without re-running the model.
        """
        if self._done:
            return self._END
        try:
            segment = next(self._source)
        except StopIteration:
            self._done = True
            return self._END
        self._buffer.append(segment)
        return segment

    def _materialize(self) -> None:
        while not self._done:
            self._next()


class _ProgressReader(threading.Thread):
    """Drains one pipe of whisper-cli and tracks its progress percent.

    whisper-cli prints "whisper_print_progress_callback: progress =
    <pct>%" to stderr, but only when -pp is given, and it flushes
    irregularly; the pipe has to be drained continuously or the child
    blocks on a full pipe and the run stalls.
    """

    #: Bytes of output kept per stream, enough for an error report.
    TAIL_BYTES = 16000

    def __init__(self, stream):
        super().__init__(daemon=True)
        self.stream = stream
        self.progress: Optional[int] = None
        self.text: bytearray = bytearray()
        self._pending = b""
        self._lock = threading.Lock()

    def run(self) -> None:
        while True:
            try:
                data = os.read(self.stream.fileno(), 4096)
            except OSError:
                break
            if not data:
                break
            self._pending += data
            self._consume()
        # A trailing line that never got its newline still counts.
        if self._pending:
            self._line(self._pending)

    def _consume(self) -> None:
        # Some builds terminate a progress line with "\r" instead of "\n".
        parts = re.split(rb"[\r\n]", self._pending)
        self._pending = parts.pop()
        for part in parts:
            self._line(part)

    def _line(self, raw: bytes) -> None:
        text = raw.decode("utf-8", "replace").strip()
        if not text:
            return
        with self._lock:
            self.text.extend(raw)
            self.text.extend(b"\n")
            # Bound the buffer: a long run must not grow it forever.
            del self.text[:-self.TAIL_BYTES]
        match = re.search(r"progress\s*=\s*(\d{1,3})\s*%", text)
        if match:
            self.progress = int(match.group(1))

    def _snapshot(self) -> bytes:
        with self._lock:
            return bytes(self.text)

    def tail(self, limit: int = 400) -> str:
        return self._snapshot().decode("utf-8", "replace").strip()[-limit:]


@register_adapter
class WhisperCppAdapter(TranscriptionAdapter):
    """Transcription via the whisper.cpp CLI (whisper-cli / main)."""

    # Binary preference: whisper-cli is the current canonical name. "main"
    # was the historic build output and is too generic to trust unless the
    # other names miss; "whisper" alone may be openai-whisper's CLI, which
    # has different flags — only accepted when nothing else matches.
    BINARY_CANDIDATES = ("whisper-cli", "main", "whisper")

    # Search paths for ggml models. WHISPERCPP_MODELS_DIR overrides all.
    MODEL_SEARCH_PATHS = (
        "~/.cache/whisper.cpp",
        "~/.cache/whisper",
        "~/.local/share/whisper.cpp",
        "~/models/whisper.cpp",
        "~/models/whisper",
        "~/models",
        "/usr/share/whisper.cpp/models",
        "/usr/share/whisper-cpp/models",
        "/usr/share/whisper-cpp",
        "/opt/whisper.cpp/models",
        "/opt/whisper-cpp/models",
    )

    #: Seconds of audio per whisper-cli run. Smaller values show progress
    #: earlier and keep more work when a run is interrupted; larger values
    #: need fewer model loads and fewer cues cut at a chunk boundary.
    CHUNK_SECONDS = 120.0

    #: Overlap between two chunks so a word cut at the boundary is heard
    #: whole by the next chunk.
    OVERLAP_SECONDS = 2.0

    #: Sample rate whisper.cpp expects.
    SAMPLE_RATE = 16000

    #: Wall-clock limit for a single chunk run when nothing sets one.
    #: whisper-cli needs many times the audio duration on a CPU-only box,
    #: so the limit is scaled with the chunk length and applies to one
    #: chunk, never to the whole file. 0 disables it.
    CHUNK_TIMEOUT_BASE = 3600.0

    #: Seconds between two intra-chunk progress lines. A chunk has to run
    #: long enough to show any: a fast model finishes a 2-minute chunk in
    #: seconds, where the per-chunk completion line is the useful report.
    PROGRESS_INTERVAL = 15.0

    def __init__(self):
        # Set when the installed whisper-cli rejected -pp: report it once
        # and keep transcribing without progress output.
        self._no_progress_flag = False

    @property
    def prefix(self) -> str:
        return "whispercpp"

    @property
    def display_name(self) -> str:
        return "whisper.cpp"

    def is_available(self) -> bool:
        try:
            self._find_binary()
            return True
        except FileNotFoundError:
            return False

    def get_model_names(self) -> List[str]:
        # Names match the ggml files in ggerganov/whisper.cpp, so
        # `<name>` resolves to `ggml-<name>.bin` both on disk and in the
        # auto-download URL. Quantized builds trade a little accuracy for
        # a much smaller file and noticeably faster CPU decoding - useful
        # on the weak machines where a full large-v3 run takes hours.
        return [
            "tiny", "base", "small", "medium", "large-v2", "large-v3",
            "large-v3-turbo",
            "tiny.en", "base.en", "small.en", "medium.en",
            # Quantized variants published by whisper.cpp (q5_0 / q5_1 /
            # q8_0 depending on the model).
            "tiny-q5_1", "tiny-q8_0",
            "base-q5_1", "base-q8_0",
            "small-q5_1", "small-q8_0",
            "medium-q5_0", "medium-q8_0",
            "large-v2-q5_0", "large-v2-q8_0",
            "large-v3-q5_0",
            "large-v3-turbo-q5_0", "large-v3-turbo-q8_0",
            "tiny.en-q5_1", "tiny.en-q8_0",
            "base.en-q5_1", "base.en-q8_0",
            "small.en-q5_1", "small.en-q8_0",
            "medium.en-q5_0", "medium.en-q8_0",
        ]

    def _find_binary(self) -> str:
        candidates = self._binary_candidates()
        if candidates:
            return candidates[0]
        raise FileNotFoundError(
            "whisper.cpp binary not found in PATH "
            f"(looked for: {', '.join(self.BINARY_CANDIDATES)})"
        )

    def _binary_candidates(self) -> List[str]:
        """All whisper.cpp binaries found in PATH, best candidate first.

        Every PATH entry is searched, not just the first hit: a stale
        build in ~/bin can shadow a working system binary, and the
        fallback below is what recovers from that.
        """
        found: List[str] = []
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        for name in self.BINARY_CANDIDATES:
            for directory in path_dirs:
                if not directory:
                    continue
                path = shutil.which(name, path=directory)
                if path and path not in found:
                    found.append(path)
        return found

    def _model_filename(self, model: str) -> str:
        return f"ggml-{model}.bin"

    def _model_search_dirs(self) -> List[str]:
        override = os.environ.get("WHISPERCPP_MODELS_DIR")
        dirs = ([override] if override else []) + [
            os.path.expanduser(p) for p in self.MODEL_SEARCH_PATHS
        ]
        dirs.append(os.path.join(os.path.dirname(__file__), "..", "models"))
        return dirs

    def _find_model_file(self, model: str, write: Callable = print) -> str:
        """Locate the ggml model file.

        Accepts an explicit path to a .bin file, or a model name that is
        resolved against the known model directories. Raises
        FileNotFoundError when the file is missing so the caller reports
        the real problem instead of letting whisper-cli fail with a usage
        dump.
        """
        if model.endswith(".bin") and os.path.isfile(model):
            return os.path.abspath(model)

        ggml_name = self._model_filename(model)
        for directory in self._model_search_dirs():
            candidate = os.path.join(directory, ggml_name)
            if os.path.isfile(candidate):
                return candidate

        searched = "\n  ".join(self._model_search_dirs())
        # Not on disk yet: whisper model files are usually downloaded on
        # first use, so do that here instead of failing. The other backends
        # (faster-whisper, HF) download transparently; this one should too,
        # so a fresh machine can run `wsub whispercpp:medium.en ...` without
        # a manual fetch step.
        downloaded = self._download_model(model, write)
        if downloaded:
            return downloaded

        raise FileNotFoundError(
            f"whisper.cpp model file '{ggml_name}' not found. Searched:\n  {searched}\n"
            "Download the ggml model (https://huggingface.co/ggerganov/whisper.cpp) "
            "or point WHISPERCPP_MODELS_DIR at the directory holding it."
        )

    def _models_dir(self) -> str:
        """Where downloaded models go: WHISPERCPP_MODELS_DIR, or the repo's
        models/ directory (already searched and already on the search path).
        """
        override = os.environ.get("WHISPERCPP_MODELS_DIR")
        if override:
            return override
        default = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models"))
        os.makedirs(default, exist_ok=True)
        return default

    def _download_model(self, model: str, write: Callable) -> Optional[str]:
        """Download a ggml model, returning its path or None on failure.

        Downloads to a `.part` file first and renames on success, so an
        interrupted download does not leave a truncated file that a later
        run would think is a complete model.
        """
        if model not in self.get_model_names():
            write(f"Unknown whisper.cpp model '{model}'")
            return None

        dest_dir = self._models_dir()
        ggml_name = self._model_filename(model)
        dest = os.path.join(dest_dir, ggml_name)
        part = dest + ".part"

        url = (
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
            f"{ggml_name}"
        )

        try:
            os.makedirs(dest_dir, exist_ok=True)
            if os.path.exists(part):
                os.remove(part)

            result = subprocess.run(
                ["curl", "-L", "-f", "--progress-bar", "-o", part, url],
                capture_output=False, text=True, check=False,
            )
            if result.returncode != 0 or not os.path.isfile(part):
                write(
                    f"Download failed for {ggml_name}: curl exited "
                    f"{result.returncode}"
                )
                if os.path.exists(part):
                    os.remove(part)
                return None

            size = os.path.getsize(part)
            if size <= 0:
                write(f"Downloaded file for {ggml_name} is empty")
                os.remove(part)
                return None

            os.rename(part, dest)
            write(
                f"Downloaded whisper.cpp model '{model}' "
                f"({size / 1024 / 1024:.1f} MB) to {dest}"
            )
            return dest
        except Exception as e:
            write(f"Could not download {ggml_name}: {e}")
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
            return None

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        **kwargs,
    ) -> Tuple[Any, Any]:
        """Transcribe chunk by chunk, yielding cues while the CLI works.

        Returns a lazily filled segment sequence and an ``Info`` object.
        The caller writes every cue into the unfinished subtitle as it
        arrives, so an interrupted run keeps the work it already did.
        """
        binaries = self._binary_candidates()
        if not binaries:
            raise FileNotFoundError(
                "whisper.cpp binary not found in PATH "
                f"(looked for: {', '.join(self.BINARY_CANDIDATES)})"
            )
        model_file = self._find_model_file(model, write)

        chunk_seconds = self._number(
            kwargs.get("chunk_seconds"), "WHISPERCPP_CHUNK_SECONDS", self.CHUNK_SECONDS
        )
        overlap = min(
            self._number(
                kwargs.get("overlap_seconds"),
                "WHISPERCPP_OVERLAP_SECONDS",
                self.OVERLAP_SECONDS,
            ),
            chunk_seconds * 0.25,
        )
        # One chunk may not take longer than this. The old fixed 3600s
        # covered the whole file, so a CPU run over a full episode was
        # killed with nothing written; the limit is now per chunk and
        # scales with how much audio that chunk holds.
        timeout = self._number(
            kwargs.get("timeout"),
            "WHISPERCPP_TIMEOUT",
            self.CHUNK_TIMEOUT_BASE * max(1.0, chunk_seconds / self.CHUNK_SECONDS),
        )
        threads = int(kwargs.get("cpu_threads") or os.cpu_count() or 4)

        workdir = self._workdir(audio_file)
        try:
            wav_path = self._to_wav(audio_file, workdir, write)
            duration = self._wav_duration(wav_path)
            chunks = self._chunk_wav(wav_path, workdir, chunk_seconds, overlap)
            cache = self._cache_dir(
                model, model_file, wav_path, language, temperature,
                chunk_seconds, overlap,
            )
        except Exception:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

        if len(chunks) > 1:
            write(
                f"whisper.cpp: {len(chunks)} chunks of {chunk_seconds:.0f}s "
                f"({_hms(duration)} of audio, {timeout:.0f}s limit per chunk); "
                f"finished chunks are cached for a resume"
            )
        elif duration:
            write(f"whisper.cpp: single chunk ({_hms(duration)} of audio)")

        segments = self._stream_chunks(
            binaries, model_file, chunks, language, temperature, threads,
            timeout, write, workdir, cache, duration, chunk_seconds,
        )
        info = type("Info", (), {
            "duration": duration,
            "language": language or "auto",
            "word_count": 0,
        })()

        def _closing_iterator() -> Iterator[Segment]:
            try:
                yield from segments
            finally:
                shutil.rmtree(workdir, ignore_errors=True)

        return SegmentStream(_closing_iterator()), info

    # ---------- chunk engine ----------

    def _stream_chunks(
        self,
        binaries: List[str],
        model_file: str,
        chunks: List[Tuple[str, float]],
        language: Optional[str],
        temperature: float,
        threads: int,
        timeout: float,
        write: Callable,
        workdir: str,
        cache: Optional[str],
        duration: float,
        chunk_seconds: float,
    ) -> Iterator[Segment]:
        """Transcribe piece by piece and yield the cues of each piece."""
        emitted_until = 0.0
        started = time.time()
        done = 0

        try:
            for index, (chunk_path, offset) in enumerate(chunks):
                label = f"{index + 1}/{len(chunks)}"
                chunk_audio = min(chunk_seconds, duration - offset) if duration else 0.0

                srt_text = None
                if cache is not None:
                    srt_text = self._cached_chunk(cache, index)
                    if srt_text is not None:
                        write(f"whisper.cpp: chunk {label} reused from cache")

                if srt_text is None:
                    srt_text, elapsed = self._run_chunk(
                        binaries, model_file, chunk_path, workdir, index, language,
                        temperature, threads, timeout, write, label,
                    )
                    if cache is not None:
                        self._store_chunk(cache, index, srt_text)

                    summary = (
                        f"whisper.cpp: chunk {label} done ({_hms(chunk_audio)} of "
                        f"audio in {_hms(elapsed)}"
                    )
                    speed = chunk_audio / elapsed if elapsed and chunk_audio > 0 else 0.0
                    if speed > 0:
                        summary += f" = {speed:.1f}x realtime"
                    remaining_audio = (
                        max(0.0, duration - offset - chunk_audio) if duration else 0.0
                    )
                    if speed > 0 and remaining_audio > 0:
                        summary += f", ETA {_hms(remaining_audio / speed)}"
                    write(summary + ")")

                for segment in self._parse_srt_output(srt_text):
                    # A cue starting inside the region the previous chunk
                    # already covered is that chunk's cut-off overlap tail:
                    # this chunk hears it whole, so drop the broken repeat.
                    if index and segment.start + offset < emitted_until - 0.05:
                        continue
                    segment.start += offset
                    segment.end += offset
                    emitted_until = max(emitted_until, segment.end)
                    yield segment

                done = index + 1
        except WhisperCppStopped:
            # The pipeline asked to stop: end the stream quietly so the
            # caller keeps the unfinished subtitle for a resume instead
            # of treating it as a failure.
            write(f"whisper.cpp: stopped after {done} of {len(chunks)} chunk(s)")
            return

        if chunks:
            write(
                f"whisper.cpp: {len(chunks)} chunk(s) transcribed in "
                f"{_hms(time.time() - started)}"
            )

    def _run_chunk(
        self,
        binaries: List[str],
        model_file: str,
        chunk_path: str,
        workdir: str,
        index: int,
        language: Optional[str],
        temperature: float,
        threads: int,
        timeout: float,
        write: Callable,
        label: str,
    ) -> Tuple[str, float]:
        out_base = os.path.join(workdir, f"out-{index:04d}")
        srt_path = out_base + ".srt"

        result = None
        elapsed = 0.0
        for binary in binaries:
            cmd = self._chunk_command(
                binary, model_file, chunk_path, out_base, language, temperature, threads
            )
            write(f"Running whisper.cpp (chunk {label}): {' '.join(cmd)}")
            result, elapsed = self._run_process(cmd, timeout, write, label)
            if result is None:
                raise WhisperCppStopped(f"stopped during chunk {label}")
            if result.returncode != 0 and self._is_broken_binary(result):
                # The dynamic loader failed (e.g. missing
                # libggml-cpu.so). Try the next candidate binary.
                write(
                    f"whisper.cpp binary {binary} is broken "
                    f"({self._error_summary(result)}); trying the next one"
                )
                continue
            if result.returncode != 0 and self._rejects_progress_flag(result):
                # An older build knows no -pp: run the same chunk without
                # it once, and without it forever after.
                self._no_progress_flag = True
                write(
                    f"whisper.cpp {binary} does not support -pp; "
                    f"continuing without progress output"
                )
                cmd = self._chunk_command(
                    binary, model_file, chunk_path, out_base, language,
                    temperature, threads,
                )
                write(f"Running whisper.cpp (chunk {label}): {' '.join(cmd)}")
                result, elapsed = self._run_process(cmd, timeout, write, label)
                if result is None:
                    raise WhisperCppStopped(f"stopped during chunk {label}")
            break

        if result is None:
            raise RuntimeError("whisper.cpp did not run")
        if result.returncode != 0:
            raise RuntimeError(
                f"whisper.cpp exited {result.returncode}: "
                f"{self._error_summary(result)}"
            )

        if not os.path.exists(srt_path):
            raise RuntimeError(
                f"whisper.cpp did not produce {srt_path}; "
                f"stderr: {(result.stderr or '')[-200:]}"
            )
        with open(srt_path, "r", encoding="utf-8") as handle:
            return handle.read(), elapsed

    def _run_process(
        self, cmd: List[str], timeout: float, write: Callable, label: str
    ) -> Tuple[Optional[subprocess.CompletedProcess], float]:
        """Run one whisper-cli invocation, reporting progress.

        Returns (None, elapsed) when the pipeline asked to stop, and
        raises WhisperCppTimeout when the wall-clock limit is reached.
        """
        started = time.time()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        readers = [_ProgressReader(proc.stderr), _ProgressReader(proc.stdout)]
        for reader in readers:
            reader.start()

        stopped = False
        timeout_detail = None
        deadline = started + timeout if timeout and timeout > 0 else None
        last_report = 0.0
        interval = self._number(
            None, "WHISPERCPP_PROGRESS_SECONDS", self.PROGRESS_INTERVAL
        )

        while True:
            try:
                proc.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                pass

            now = time.time()
            if self._stop_requested():
                stopped = True
                break
            if deadline is not None and now > deadline:
                timeout_detail = (
                    f"whisper.cpp chunk {label} hit its {_hms(timeout)} limit "
                    f"after {_hms(now - started)} of work, so its cues are lost. "
                    f"Raise it with WHISPERCPP_TIMEOUT=0 (no limit), or let one "
                    f"chunk cover less audio with WHISPERCPP_CHUNK_SECONDS, or "
                    f"use a faster model (a smaller one, or a quantised ggml "
                    f"model such as large-v3-q5_0)."
                )
                break
            if now - last_report >= interval:
                last_report = now
                progress = self._progress(readers)
                if progress is not None:
                    write(
                        f"whisper.cpp: {progress}% of chunk {label} "
                        f"(elapsed {_hms(now - started)})"
                    )

        if timeout_detail is not None:
            self._terminate(proc)
            for reader in readers:
                reader.join(timeout=2)
            raise WhisperCppTimeout(timeout_detail)
        if stopped:
            self._terminate(proc)
            for reader in readers:
                reader.join(timeout=2)
            write(f"whisper.cpp: chunk {label} interrupted after {_hms(time.time() - started)}")
            return None, time.time() - started

        for reader in readers:
            reader.join(timeout=5)
        # system_info carries the thread/simd/backend summary of the run,
        # which is what tells a slow transcription why it is slow.
        system_info = next(
            (
                line.strip()
                for reader in readers
                for line in reader._snapshot().decode("utf-8", "replace").splitlines()
                if "system_info" in line
            ),
            None,
        )
        if system_info:
            write(system_info)

        elapsed = time.time() - started
        return (
            subprocess.CompletedProcess(
                cmd, proc.returncode, stdout="", stderr=readers[0].tail()
            ),
            elapsed,
        )

    @staticmethod
    def _progress(readers: List[_ProgressReader]) -> Optional[int]:
        for reader in readers:
            if reader.progress is not None:
                return reader.progress
        return None

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        """Stop a whisper-cli run, escalating to SIGKILL when it stalls."""
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    @staticmethod
    def _stop_requested() -> bool:
        """True when the pipeline asked the transcription to stop (Ctrl+C)."""
        module = sys.modules.get("transcribe")
        return bool(module and getattr(module, "_STOP_REQUESTED", False))

    def _chunk_command(
        self,
        binary: str,
        model_file: str,
        chunk_path: str,
        out_base: str,
        language: Optional[str],
        temperature: float,
        threads: int,
    ) -> List[str]:
        # -of pins the output name; whisper-cli otherwise writes
        # <input>.srt next to the media file. The workdir keeps that
        # write from clobbering a sibling .srt of the same name.
        cmd = [
            binary,
            "-m", model_file,
            "-f", chunk_path,
            "-of", out_base,
            "-osrt",
            "-t", str(threads),
        ]
        if not self._no_progress_flag:
            # -pp makes the CLI report its progress on stderr; with -np
            # the subtitle file would be the only feedback there is.
            cmd.append("-pp")
        # No -l keeps whisper-cli's own default; an explicit language is
        # forwarded, "auto" asks for detection.
        if language and language != "none":
            cmd.extend(["-l", str(language)])
        if temperature:
            cmd.extend(["-tp", str(temperature)])
        return cmd

    @staticmethod
    def _rejects_progress_flag(result: subprocess.CompletedProcess) -> bool:
        """True when this whisper-cli build does not know -pp."""
        text = ((result.stderr or "") + (result.stdout or "")).lower()
        return "unknown argument" in text and ("-pp" in text or "print-progress" in text)

    @staticmethod
    def _is_broken_binary(result: subprocess.CompletedProcess) -> bool:
        """True when the binary itself failed to start (missing libraries)."""
        if result.returncode != 127:
            return False
        output = (result.stderr or "") + (result.stdout or "")
        return "shared libraries" in output or "cannot open shared object" in output

    @staticmethod
    def _error_summary(result: subprocess.CompletedProcess) -> str:
        """Extract whisper-cli's error lines; its usage dump is noise."""
        output = (result.stderr or "") + "\n" + (result.stdout or "")
        errors = [line.strip() for line in output.splitlines()
                  if line.strip().lower().startswith("error")]
        if errors:
            return " | ".join(errors[:3])
        tail = (result.stderr or result.stdout or "").strip()
        return tail[-400:] if tail else "no output"

    # ---------- audio preparation ----------

    def _workdir(self, audio_file: str) -> str:
        """Scratch directory for the split audio and the chunk subtitles.

        The media directory comes first: a 16 kHz mono wav of a
        90-minute episode is ~170 MB, and that directory is on disk while
        /tmp is often a tmpfs. WHISPERCPP_TMPDIR overrides; the system
        temp dir is the fallback for a read-only media directory.
        """
        override = os.environ.get("WHISPERCPP_TMPDIR")
        candidates = [override] if override else [
            os.path.dirname(os.path.abspath(audio_file)),
            tempfile.gettempdir(),
        ]
        for directory in candidates:
            if not directory:
                continue
            try:
                return tempfile.mkdtemp(prefix=".whispercpp-", dir=directory)
            except OSError:
                continue
        return tempfile.mkdtemp(prefix="whispercpp-")

    def _to_wav(self, audio_file: str, workdir: str, write: Callable) -> str:
        """16 kHz mono PCM wav for whisper-cli."""
        if audio_file.lower().endswith(".wav"):
            try:
                with wave.open(audio_file, "rb") as probe:
                    if (
                        probe.getframerate() == self.SAMPLE_RATE
                        and probe.getnchannels() == 1
                        and probe.getsampwidth() == 2
                    ):
                        return audio_file
            except (wave.Error, OSError):
                # Not readable as PCM: hand it to whisper-cli untouched,
                # which is what the previous implementation did for every
                # .wav input.
                return audio_file

        wav_path = os.path.join(workdir, "source.wav")
        write("Converting audio to 16kHz mono WAV for whisper.cpp...")
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-i", audio_file,
            "-ar", str(self.SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le",
            wav_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except FileNotFoundError:
            raise RuntimeError("ffmpeg is required to convert the audio for whisper.cpp")
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"Audio conversion failed: {detail[-400:]}")
        return wav_path

    @staticmethod
    def _wav_duration(wav_path: str) -> float:
        try:
            with wave.open(wav_path, "rb") as handle:
                rate = handle.getframerate()
                return handle.getnframes() / float(rate) if rate else 0.0
        except (wave.Error, OSError):
            return 0.0

    def _chunk_wav(
        self, wav_path: str, workdir: str, chunk_seconds: float, overlap: float
    ) -> List[Tuple[str, float]]:
        """Split the wav into overlapping chunks.

        Returns (chunk path, offset in seconds) pairs. The overlap lets
        the next chunk hear a word that was cut in two at the boundary.
        A file that cannot be split (unknown length, not real PCM) is
        transcribed as a single chunk.
        """
        if chunk_seconds <= 0:
            return [(wav_path, 0.0)]
        try:
            with wave.open(wav_path, "rb") as source:
                chunks = self._chunk_open_wav(source, workdir, chunk_seconds, overlap)
        except (wave.Error, OSError):
            return [(wav_path, 0.0)]
        return chunks or [(wav_path, 0.0)]

    def _chunk_open_wav(
        self, source, workdir: str, chunk_seconds: float, overlap: float
    ) -> List[Tuple[str, float]]:
        rate = source.getframerate()
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        total_frames = source.getnframes()
        if not rate or total_frames <= 0:
            return []

        chunks: List[Tuple[str, float]] = []
        chunk_frames = max(1, int(chunk_seconds * rate))
        overlap_frames = min(int(overlap * rate), chunk_frames // 2)
        step = max(1, chunk_frames - overlap_frames)

        index = 0
        position = 0
        while position < total_frames:
            frames = min(chunk_frames, total_frames - position)
            source.setpos(position)
            frames_data = source.readframes(frames)
            chunk_path = os.path.join(workdir, f"chunk-{index:04d}.wav")
            with wave.open(chunk_path, "wb") as out:
                out.setnchannels(channels)
                out.setsampwidth(sample_width)
                out.setframerate(rate)
                out.writeframes(frames_data)
            chunks.append((chunk_path, position / float(rate)))
            index += 1
            # The last piece reaches the end of the file.
            if frames < chunk_frames:
                break
            position += step
        return chunks

    # ---------- resume cache ----------

    def _cache_dir(
        self,
        model: str,
        model_file: str,
        wav_path: str,
        language: Optional[str],
        temperature: float,
        chunk_seconds: float,
        overlap: float,
    ) -> Optional[str]:
        """Directory holding the chunks that are already transcribed.

        Keyed by everything that changes the transcription of a chunk, so
        a different model, language or audio file gets its own entries and
        an interrupted run resumes exactly where it stopped. WHISPERCPP_NO_CACHE
        disables it outright.
        """
        if os.environ.get("WHISPERCPP_NO_CACHE") or chunk_seconds <= 0:
            return None
        try:
            model_stat = os.stat(model_file)
            audio_stat = os.stat(wav_path)
        except OSError:
            return None
        key = "|".join([
            "whispercpp-chunk-cache-v1",
            str(model), os.path.realpath(model_file),
            str(model_stat.st_size), str(model_stat.st_mtime_ns),
            os.path.realpath(wav_path), str(audio_stat.st_size),
            str(audio_stat.st_mtime_ns),
            str(language or ""), str(temperature or 0.0),
            f"{chunk_seconds:g}", f"{overlap:g}",
        ])
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
        base = os.environ.get("WHISPERCPP_CACHE_DIR") or os.path.join(
            os.path.expanduser("~"), ".cache", "whisper-subs", "whispercpp"
        )
        directory = os.path.join(base, digest)
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            return None
        return directory

    @staticmethod
    def _cached_chunk(cache_dir: str, index: int) -> Optional[str]:
        path = os.path.join(cache_dir, f"chunk-{index:04d}.srt")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read() or None
        except OSError:
            return None

    @staticmethod
    def _store_chunk(cache_dir: str, index: int, srt_text: str) -> None:
        path = os.path.join(cache_dir, f"chunk-{index:04d}.srt")
        partial = path + ".part"
        try:
            # Write aside and rename: an interrupted run must never leave
            # a half-written chunk behind that reads as a valid hit.
            with open(partial, "w", encoding="utf-8") as handle:
                handle.write(srt_text)
            os.replace(partial, path)
        except OSError:
            try:
                os.remove(partial)
            except OSError:
                pass

    @staticmethod
    def _number(value, env_name: str, default: float) -> float:
        """Numeric setting from the call, the environment, or the default."""
        for candidate in (value, os.environ.get(env_name)):
            try:
                if candidate is None or candidate == "":
                    continue
                return float(candidate)
            except (TypeError, ValueError):
                continue
        return float(default)

    # SRT timestamps: 1-2 digit hours are legal in practice; tolerate them.
    _TIME_RE = re.compile(
        r"(\d{1,2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2},\d{3})"
    )

    @classmethod
    def _parse_srt_output(cls, srt_text: str) -> List[Segment]:
        segments: List[Segment] = []
        blocks = srt_text.strip().split("\n\n")
        for block in blocks:
            lines = [line for line in block.strip().splitlines() if line.strip()]
            if len(lines) < 2:
                continue
            # Locate the timestamp line (usually line 1, after the index).
            ts_idx = next(
                (i for i, line in enumerate(lines) if cls._TIME_RE.search(line)),
                None,
            )
            if ts_idx is None:
                continue
            match = cls._TIME_RE.search(lines[ts_idx])
            text = "\n".join(lines[ts_idx + 1:]).strip()
            if not text:
                continue
            segments.append(Segment(
                start=cls._srt_to_seconds(match.group(1)),
                end=cls._srt_to_seconds(match.group(2)),
                text=text,
            ))
        return segments

    @staticmethod
    def _srt_to_seconds(time_str: str) -> float:
        parts = re.split("[:,]", time_str)
        return (
            int(parts[0]) * 3600
            + int(parts[1]) * 60
            + int(parts[2])
            + int(parts[3]) / 1000.0
        )