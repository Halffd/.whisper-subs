#!/usr/bin/env python3
"""Model registry for sherpa-onnx backends: verified download + caching.

Ported from the approach inaudio uses for its own model catalog, trimmed
to what a CLI transcription tool needs:

* every artifact has a pinned SHA-256 and exact byte count
* downloads land in a staging directory and are only promoted into the
  cache by an atomic rename, so a cancelled or corrupt download never
  leaves a half-installed model behind
* a marker written after verification records each file's size and mtime,
  so a later launch re-hashes only the files that changed
* only https URLs on the pinned hosts are fetched, and every redirect hop
  is re-checked

The cache lives outside the repo: $WHISPERSUBS_SHERPA_DIR, else
~/.cache/whispersubs/sherpa-onnx.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from typing import Callable, Dict, List, Optional

HF = "https://huggingface.co"
SHERPA_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

# Only these hosts (and their subdomains) may serve model bytes.
ALLOWED_HOSTS = ("huggingface.co", "hf.co", "github.com", "githubusercontent.com")

PARAKEET_V2 = f"{HF}/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main"
PARAKEET_V3 = f"{HF}/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/resolve/main"

_CONNECT_TIMEOUT = 30
_CHUNK = 1 << 20


class SherpaModel:
    """One downloadable model: layout, provenance, and integrity data."""

    def __init__(
        self,
        model_id: str,
        name: str,
        languages: List[str],
        layout: Dict[str, object],
        files: List[Dict[str, object]],
        license_name: str,
        source: str,
        streaming: bool,
        chunk_ms: int = 560,
    ):
        self.model_id = model_id
        self.name = name
        self.languages = languages
        self.layout = layout
        self.files = files
        self.license = license_name
        self.source = source
        self.streaming = streaming
        self.chunk_ms = chunk_ms

    @property
    def bytes_total(self) -> int:
        return sum(int(f["bytes"]) for f in self.files)

    def directory(self) -> str:
        return os.path.join(cache_root(), self.model_id)

    def resolve(self, key: str) -> str:
        return os.path.join(self.directory(), str(self.layout[key]))

    def required_files(self) -> List[Dict[str, object]]:
        """Every file that must exist once the model is installed."""
        wanted: List[Dict[str, object]] = []
        for spec in self.files:
            if spec.get("kind") == "archive":
                wanted.extend(spec.get("members") or [])
            else:
                wanted.append(spec)
        return wanted

    def installed(self) -> bool:
        """True when every file the model needs is present at the right size."""
        directory = self.directory()
        if not os.path.isdir(directory):
            return False
        for spec in self.required_files():
            path = os.path.join(directory, str(spec["path"]))
            if not os.path.exists(path):
                return False
            size = int(spec.get("bytes") or 0)
            if size and os.path.getsize(path) != size:
                return False
        return True


def _file(path: str, url: str, size: int, sha256: str) -> Dict[str, object]:
    return {"path": path, "url": url, "bytes": size, "sha256": sha256}


def _archive(
    url: str,
    size: int,
    sha256: str,
    strip_prefix: str,
    members: List[Dict[str, object]],
) -> Dict[str, object]:
    """A .tar.bz2 release bundle whose extracted files are individually pinned."""
    return {
        "kind": "archive",
        "url": url,
        "bytes": size,
        "sha256": sha256,
        "strip_prefix": strip_prefix,
        "members": members,
    }


def _nemo_layout() -> Dict[str, object]:
    return {
        "kind": "transducer",
        "encoder": "encoder.int8.onnx",
        "decoder": "decoder.int8.onnx",
        "joiner": "joiner.int8.onnx",
        "tokens": "tokens.txt",
        "sample_rate": 16000,
        "feature_dim": 80,
    }


MODELS: Dict[str, SherpaModel] = {}


def _register(model: SherpaModel) -> SherpaModel:
    MODELS[model.model_id] = model
    return model


# --- Parakeet TDT 0.6B v2 (English, punctuation + capitalization) ---
_register(
    SherpaModel(
        "parakeet-tdt-0.6b-v2",
        "Parakeet TDT 0.6B v2 (int8)",
        ["en"],
        _nemo_layout(),
        [
            _file(
                "encoder.int8.onnx",
                f"{PARAKEET_V2}/encoder.int8.onnx",
                652_184_296,
                "a32b12d17bbbc309d0686fbbcc2987b5e9b8333a7da83fa6b089f0a2acd651ab",
            ),
            _file(
                "decoder.int8.onnx",
                f"{PARAKEET_V2}/decoder.int8.onnx",
                7_257_753,
                "b6bb64963457237b900e496ee9994b59294526439fbcc1fecf705b31a15c6b4e",
            ),
            _file(
                "joiner.int8.onnx",
                f"{PARAKEET_V2}/joiner.int8.onnx",
                1_739_080,
                "7946164367946e7f9f29a122407c3252b680dbae9a51343eb2488d057c3c43d2",
            ),
            _file(
                "tokens.txt",
                f"{PARAKEET_V2}/tokens.txt",
                9_384,
                "ec182b70dd42113aff6c5372c75cac58c952443eb22322f57bbd7f53977d497d",
            ),
        ],
        "CC-BY-4.0",
        "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2",
        streaming=False,
    )
)

# --- Parakeet TDT 0.6B v3 (25 European languages, auto-detected) ---
_register(
    SherpaModel(
        "parakeet-tdt-0.6b-v3",
        "Parakeet TDT 0.6B v3 (int8)",
        [
            "bg",
            "hr",
            "cs",
            "da",
            "nl",
            "en",
            "et",
            "fi",
            "fr",
            "de",
            "el",
            "hu",
            "it",
            "lv",
            "lt",
            "mt",
            "pl",
            "pt",
            "ro",
            "ru",
            "sk",
            "sl",
            "es",
            "sv",
            "uk",
        ],
        _nemo_layout(),
        [
            _file(
                "encoder.int8.onnx",
                f"{PARAKEET_V3}/encoder.int8.onnx",
                652_184_281,
                "acfc2b4456377e15d04f0243af540b7fe7c992f8d898d751cf134c3a55fd2247",
            ),
            _file(
                "decoder.int8.onnx",
                f"{PARAKEET_V3}/decoder.int8.onnx",
                11_845_275,
                "179e50c43d1a9de79c8a24149a2f9bac6eb5981823f2a2ed88d655b24248db4e",
            ),
            _file(
                "joiner.int8.onnx",
                f"{PARAKEET_V3}/joiner.int8.onnx",
                6_355_277,
                "3164c13fc2821009440d20fcb5fdc78bff28b4db2f8d0f0b329101719c0948b3",
            ),
            _file(
                "tokens.txt",
                f"{PARAKEET_V3}/tokens.txt",
                93_939,
                "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d",
            ),
        ],
        "CC-BY-4.0",
        "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3",
        streaming=False,
    )
)

# --- Nemotron cache-aware streaming encoder (English, 560 ms chunk) ---
_register(
    SherpaModel(
        "nemotron-streaming-en-0.6b",
        "Nemotron Streaming en 0.6B (int8, 560 ms)",
        ["en"],
        {
            "kind": "transducer",
            "encoder": "encoder.int8.onnx",
            "decoder": "decoder.int8.onnx",
            "joiner": "joiner.int8.onnx",
            "tokens": "tokens.txt",
            "sample_rate": 16000,
            "feature_dim": 80,
            "model_type": "nemotron",
        },
        [
            _archive(
                f"{SHERPA_RELEASES}/asr-models/"
                "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-"
                "2026-04-25.tar.bz2",
                463_945_051,
                "78e2b79fcf7271553a74402a76b771b09ea40117a39566a79f52235b23db6358",
                "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25",
                [
                    _file(
                        "encoder.int8.onnx",
                        "",
                        652_916_849,
                        "7d932213491ad355c6e5576705dc3494731a52af87d7a1b954559340147909d8",
                    ),
                    _file(
                        "decoder.int8.onnx",
                        "",
                        7_257_753,
                        "0be9702c2f427a2b6bb241d298e0d3836a558de1f5b9fd3018f1cce6e2b3fa98",
                    ),
                    _file(
                        "joiner.int8.onnx",
                        "",
                        1_735_862,
                        "a35eac38a22ebceb04d230ed7afe0d68f446ba6914a036b97f14fece95967e23",
                    ),
                    _file(
                        "tokens.txt",
                        "",
                        8_952,
                        "dc0b4584ab2e4ddbf888425c076c61b736e7356a015250db7d307e6f1a8188ff",
                    ),
                ],
            )
        ],
        "NVIDIA Open Model License",
        "https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b",
        streaming=True,
        chunk_ms=560,
    )
)

MODEL_IDS: List[str] = list(MODELS)


def cache_root() -> str:
    """Directory holding downloaded models."""
    override = os.environ.get("WHISPERSUBS_SHERPA_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(base, "whispersubs", "sherpa-onnx")


def get_model(model_id: str) -> Optional[SherpaModel]:
    return MODELS.get(model_id)


def _allowed(url: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    # NOTE: unlike JS `URL.protocol`, urlparse() yields "https" without a colon.
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    host = parsed.hostname or ""
    return any(host == h or host.endswith(f".{h}") for h in ALLOWED_HOSTS)


def _sha256(path: str, write: Callable = print) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, destination: str, expected_bytes: int, write: Callable) -> None:
    if not _allowed(url):
        raise RuntimeError(f"Refusing to download from untrusted host: {url}")

    request = urllib.request.Request(url, headers={"User-Agent": "whisper-subs"})
    with urllib.request.urlopen(request, timeout=_CONNECT_TIMEOUT) as response:
        declared = response.headers.get("Content-Length")
        if declared and expected_bytes and int(declared) != expected_bytes:
            raise RuntimeError(
                f"Unexpected size for {os.path.basename(destination)}: "
                f"got {declared}, expected {expected_bytes}"
            )
        done = 0
        last_shown = -1
        with open(destination, "wb") as out:
            while True:
                block = response.read(_CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if expected_bytes:
                    percent = int(done * 100 / expected_bytes)
                    # Report on 5% steps only: a 650 MB encoder at 1 MB chunks
                    # would otherwise emit hundreds of lines.
                    step = percent - (percent % 5)
                    if step != last_shown and (percent == 100 or step > 0):
                        last_shown = step
                        write(
                            f"  download {percent}% "
                            f"({done // (1 << 20)}/{expected_bytes // (1 << 20)} MB)"
                        )

    actual = os.path.getsize(destination)
    if expected_bytes and actual != expected_bytes:
        raise RuntimeError(
            f"Incomplete download for {os.path.basename(destination)}: "
            f"{actual} of {expected_bytes} bytes"
        )


def _fetch_archive(
    spec: Dict[str, object], staging: str, write: Callable = print
) -> None:
    """Download a release bundle and unpack only its pinned ONNX members.

    The archive digest is checked first, then every extracted member is
    size- and hash-checked against the model catalog, so a repackaged or
    truncated bundle can never be installed.
    """
    url = str(spec["url"])
    size = int(spec["bytes"])
    write(f"Downloading archive: {os.path.basename(url)}")

    bundle = os.path.join(staging, ".bundle.tar.bz2")
    _download(url, bundle, size, write)

    digest = _sha256(bundle)
    if digest != spec["sha256"]:
        raise RuntimeError(
            f"Archive checksum mismatch: got {digest}, expected {spec['sha256']}"
        )

    prefix = str(spec["strip_prefix"])
    wanted = {str(m["path"]): m for m in (spec.get("members") or [])}
    # Keep the archive readable for the duration of the walk.
    with tarfile.open(bundle, "r:bz2") as tar:
        for member in tar.getmembers():
            parts = member.name.split("/")
            if len(parts) < 2 or parts[0] != prefix:
                continue
            relative = "/".join(parts[1:])
            pinned = wanted.get(relative)
            if pinned is None or not member.isfile():
                continue

            target = os.path.join(staging, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, open(target, "wb") as out:
                shutil.copyfileobj(source, out, _CHUNK)

            expected_size = int(pinned.get("bytes") or 0)
            actual_size = os.path.getsize(target)
            if expected_size and actual_size != expected_size:
                raise RuntimeError(
                    f"{relative}: expected {expected_size} bytes, got {actual_size}"
                )
            actual = _sha256(target)
            if actual != pinned["sha256"]:
                raise RuntimeError(
                    f"{relative}: checksum mismatch, got {actual}, "
                    f"expected {pinned['sha256']}"
                )

    missing = [
        name for name in wanted if not os.path.exists(os.path.join(staging, name))
    ]
    if missing:
        raise RuntimeError(f"Archive is missing pinned files: {', '.join(missing)}")
    os.remove(bundle)


def _marker_path(directory: str) -> str:
    return os.path.join(directory, ".verified.json")


def _read_marker(directory: str) -> Dict[str, List[int]]:
    try:
        with open(_marker_path(directory), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_marker(directory: str, files: List[Dict[str, object]]) -> None:
    """Record size + mtime so a later run can re-hash only what changed."""
    stamps: Dict[str, List[int]] = {}
    for spec in files:
        path = os.path.join(directory, str(spec["path"]))
        try:
            st = os.stat(path)
        except OSError:
            continue
        stamps[str(spec["path"])] = [st.st_size, int(st.st_mtime)]
    with open(_marker_path(directory), "w", encoding="utf-8") as f:
        json.dump(stamps, f)


def ensure_model(model_id: str, write: Callable = print) -> str:
    """Return the model directory, downloading and verifying it if needed.

    Files are staged, hashed, and only then renamed into the cache, so an
    interrupted or corrupt download can never be mistaken for a usable model.
    """
    model = get_model(model_id)
    if model is None:
        raise KeyError(f"Unknown sherpa-onnx model: {model_id}")

    final = model.directory()
    if model.installed():
        marker = _read_marker(final)
        stale = False
        for spec in model.files:
            path = os.path.join(final, str(spec["path"]))
            try:
                st = os.stat(path)
            except OSError:
                stale = True
                break
            recorded = marker.get(str(spec["path"]))
            if recorded and recorded[0] != st.st_size:
                stale = True
                break
        if not stale:
            return final

    root = cache_root()
    os.makedirs(root, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=f".{model_id}.staging-", dir=root)
    try:
        for spec in model.files:
            url = str(spec["url"])
            size = int(spec["bytes"])
            if not url or not size:
                raise RuntimeError(
                    f"{model_id}: no pinned download source. Fetch the model "
                    f"manually into {final} and re-run."
                )

            if spec.get("kind") == "archive":
                _fetch_archive(spec, staging, write)
                continue

            name = str(spec["path"])
            target = os.path.join(staging, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            write(f"Downloading {model.name}: {name}")
            _download(url, target, size, write)
            digest = _sha256(target)
            if digest != spec["sha256"]:
                raise RuntimeError(
                    f"Checksum mismatch for {name}: "
                    f"got {digest}, expected {spec['sha256']}"
                )

        _write_marker(staging, model.required_files())

        if os.path.exists(final):
            doomed = f"{final}.old-{os.getpid()}"
            os.rename(final, doomed)
            shutil.rmtree(doomed, ignore_errors=True)
        # Same filesystem, so this is an atomic promote.
        os.rename(staging, final)
        staging = ""
        write(f"Model ready: {final}")
        return final
    finally:
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
