"""hal_model_gateway.whisper_stt — FREE local Whisper STT (optional push-to-talk).

Uses tiny/base.en from ~/.cache/whisper. First load can be slow; keep calls short.
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_model = None
_model_name: Optional[str] = None

DEFAULT_MODEL = os.environ.get("HAL_WHISPER_MODEL", "tiny")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB
TRANSCRIBE_TIMEOUT_HINT_S = 60


def stt_health() -> dict:
    cache = Path.home() / ".cache" / "whisper"
    present = []
    if cache.is_dir():
        present = sorted(p.name for p in cache.glob("*.pt"))
    return {
        "backend": "whisper",
        "ok": bool(present),
        "default_model": DEFAULT_MODEL,
        "cached_models": present,
        "loaded": _model is not None,
        "loaded_model": _model_name,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "free": True,
        "note": "First request may load the model into RAM (~seconds).",
    }


def _load_model(name: str):
    global _model, _model_name
    import whisper  # type: ignore

    if _model is not None and _model_name == name:
        return _model
    _model = whisper.load_model(name)
    _model_name = name
    return _model


def transcribe_bytes(data: bytes, filename: str = "audio.webm", model_name: Optional[str] = None) -> dict:
    if not data:
        raise ValueError("empty audio")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"audio too large (max {MAX_UPLOAD_BYTES} bytes)")

    name = (model_name or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    suffix = Path(filename).suffix or ".webm"
    if suffix.lower() not in {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".mpeg", ".mp4", ".flac"}:
        suffix = ".webm"

    with _lock:
        model = _load_model(name)
        with tempfile.NamedTemporaryFile(prefix="hal_asr_", suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        try:
            result = model.transcribe(path, language="en", fp16=False)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    text = str(result.get("text") or "").strip()
    return {
        "text": text,
        "language": result.get("language") or "en",
        "model": name,
    }
