"""WhisperCppAdapter - whisper.cpp CLI transcription.

Runs whisper-cli (or the classic main binary) as a subprocess and parses
the SRT it writes to disk. The CLI prints its transcript to stdout only
in the default text mode; -osrt writes <output-file>.srt (cli.cpp
fout_factory), so the adapter pins the name with -of and reads that file
rather than stdout.
"""
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


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
        return [
            "tiny", "base", "small", "medium", "large-v2", "large-v3",
            "tiny.en", "base.en", "small.en", "medium.en",
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

    def _find_model_file(self, model: str) -> str:
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
        downloaded = self._download_model(model, print)
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
    ) -> Tuple[List[Segment], Any]:
        binaries = self._binary_candidates()
        if not binaries:
            raise FileNotFoundError(
                "whisper.cpp binary not found in PATH "
                f"(looked for: {', '.join(self.BINARY_CANDIDATES)})"
            )
        model_file = self._find_model_file(model)

        converted_audio = audio_file
        needs_conversion = not audio_file.lower().endswith(".wav")
        if needs_conversion:
            converted_audio = self._convert_to_wav(audio_file, write)

        # -of pins the output name; whisper-cli otherwise writes
        # <input>.srt (clip.wav.srt) next to the media file. A temp dir
        # keeps that write from clobbering a sibling .srt of the same name.
        out_dir = tempfile.mkdtemp(prefix="whispercpp-")
        srt_base = os.path.join(out_dir, "out")
        srt_path = srt_base + ".srt"

        try:
            result = None
            for binary in binaries:
                cmd = [
                    binary,
                    "-m", model_file,
                    "-f", converted_audio,
                    "-of", srt_base,
                    "-osrt",
                    "-np",  # keep stdout quiet; the SRT lands on disk
                ]
                # No -l keeps whisper-cli's own default; an explicit
                # language is forwarded, "auto" asks for detection.
                if language and language != "none":
                    cmd.extend(["-l", str(language)])
                if temperature:
                    cmd.extend(["-tp", str(temperature)])
                threads = kwargs.get("cpu_threads")
                if threads:
                    cmd.extend(["-t", str(int(threads))])

                write(f"Running whisper.cpp: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=3600
                )
                if result.returncode != 0 and self._is_broken_binary(result):
                    # The dynamic loader failed (e.g. missing
                    # libggml-cpu.so). Try the next candidate binary.
                    write(
                        f"whisper.cpp binary {binary} is broken "
                        f"({self._error_summary(result)}); trying the next one"
                    )
                    continue
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
                segments = self._parse_srt_output(handle.read())

            if not segments:
                write("whisper.cpp produced no subtitle blocks (silent audio?)")

            info = type("Info", (), {
                "duration": segments[-1].end if segments else 0.0,
                "language": language or "auto",
                "word_count": 0,
            })()
            return segments, info

        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
            if needs_conversion and os.path.exists(converted_audio):
                try:
                    os.remove(converted_audio)
                except OSError:
                    pass

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

    @staticmethod
    def _convert_to_wav(audio_file: str, write: Callable = print) -> str:
        converted = audio_file + ".whispercpp.wav"
        write("Converting audio to 16kHz mono WAV for whisper.cpp...")
        cmd = [
            "ffmpeg", "-y", "-i", audio_file,
            "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
            converted,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Audio conversion failed: {result.stderr[-400:]}")
        return converted

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
