"""hal_model_gateway.piper_tts - FREE local Piper TTS for public voice.

Shipped voice: en_US-norman-medium. Additional Piper voices under
assets/voices/piper/<voice_id>/ are auto-discovered when present.
No paid APIs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

HAL_ROOT = Path(os.environ.get("HAL_ROOT", r"D:\HAL_SUPREME"))
DEFAULT_VOICE = "en_US-norman-medium"
# VOICES_DIR overrides default HAL_ROOT/assets/voices/piper (Docker volume mount)
_voices_override = os.environ.get("VOICES_DIR") or os.environ.get("HAL_VOICES_DIR")
VOICES_ROOT = Path(_voices_override) if _voices_override else (HAL_ROOT / "assets" / "voices" / "piper")
VOICE_DIR = VOICES_ROOT / DEFAULT_VOICE
DEFAULT_MODEL = VOICE_DIR / f"{DEFAULT_VOICE}.onnx"
DEFAULT_PIPER = Path(os.environ.get("HAL_PIPER_EXE", r"D:\Python312\Scripts\piper.exe"))

MAX_CHARS = 1200
SYNTH_TIMEOUT_S = 45.0

# Planned / stub voices (shown in UI even before models land). Real = on disk.
PLANNED_VOICES = [
    {"id": "en_US-norman-medium", "label": "HAL Norman (default, clear male)", "style": "neutral"},
    {"id": "en_US-lessac-medium", "label": "Lessac (expressive female)", "style": "warm"},
    {"id": "en_US-amy-medium", "label": "Amy (bright female)", "style": "bright"},
    {"id": "en_GB-alan-medium", "label": "Alan (UK calm male)", "style": "calm"},
]

_lock = threading.Lock()


def _which_piper() -> Optional[Path]:
    for candidate in (
        DEFAULT_PIPER,
        Path(shutil.which("piper") or ""),
        VOICES_ROOT / "piper.exe",
    ):
        if candidate and candidate.is_file():
            return candidate
    return None


def _voice_model_paths(voice_id: str) -> tuple[Path, Path]:
    model = VOICES_ROOT / voice_id / f"{voice_id}.onnx"
    cfg = Path(str(model) + ".json")
    return model, cfg


def list_voices() -> list[dict]:
    """Return installed + planned voices for the voice picker."""
    installed = set()
    if VOICES_ROOT.is_dir():
        for d in VOICES_ROOT.iterdir():
            if not d.is_dir():
                continue
            model, cfg = _voice_model_paths(d.name)
            if model.is_file() and cfg.is_file():
                installed.add(d.name)

    out: list[dict] = []
    seen = set()
    for row in PLANNED_VOICES:
        vid = row["id"]
        seen.add(vid)
        item = dict(row)
        if vid in installed:
            item["status"] = "ready"
            item["backend"] = "piper"
        else:
            item.setdefault("status", "planned")
        out.append(item)

    for vid in sorted(installed):
        if vid in seen:
            continue
        out.append({
            "id": vid,
            "label": vid,
            "style": "neutral",
            "status": "ready",
            "backend": "piper",
        })
    return out


def voice_health() -> dict:
    exe = _which_piper()
    model, cfg = _voice_model_paths(DEFAULT_VOICE)
    ready = [v["id"] for v in list_voices() if v.get("status") == "ready"]
    return {
        "backend": "piper",
        "voice": DEFAULT_VOICE,
        "ok": bool(exe and model.is_file() and cfg.is_file()),
        "piper_exe": str(exe) if exe else None,
        "model": str(model) if model.is_file() else None,
        "max_chars": MAX_CHARS,
        "typical_latency_s": 3.6,
        "free": True,
        "voices_ready": ready,
        "voices": list_voices(),
    }


def prepare_speech_text(raw: str) -> str:
    import re as _re

    text = (raw or "").strip()
    if not text:
        return ""
    try:
        from hal_voice.speech_renderer import render_for_speech

        text = render_for_speech(text).text
    except Exception:
        pass
    # Always normalize for TTS (renderer may leave remnants)
    text = _re.sub(r"```[\s\S]*?```", " ", text)
    text = _re.sub(r"`([^`]+)`", r"\1", text)
    text = _re.sub(r"https?://\S+", " link ", text)
    text = _re.sub(
        r"(?m)^\s*(?:[A-G](?:#|b)?(?:maj|min|m|dim|aug|sus\d*)?\d*(?:/[A-G](?:#|b)?)?[\s|/,.-]*)+$",
        " ",
        text,
    )
    text = _re.sub(r"[|]+", " ", text)
    text = _re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 1].rsplit(" ", 1)[0] + "..."
    return text



def synthesize_wav(
    text: str,
    voice: Optional[str] = None,
    *,
    style: Optional[str] = None,
    length_scale: Optional[float] = None,
) -> bytes:
    """Synthesize WAV bytes with Piper. Raises RuntimeError on failure.

    style='singing' or 'song' slightly slows pacing (more melodic for lyrics).
    """
    speech = prepare_speech_text(text)
    if not speech:
        raise ValueError("empty speech text")

    voice_id = (voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE
    model, cfg = _voice_model_paths(voice_id)
    if not model.is_file() or not cfg.is_file():
        voice_id = DEFAULT_VOICE
        model, cfg = _voice_model_paths(voice_id)

    exe = _which_piper()
    if not exe:
        raise RuntimeError("piper executable not found")
    if not model.is_file() or not cfg.is_file():
        raise RuntimeError(f"piper model missing: {model}")

    # Melodic / singing pacing — Piper --length-scale > 1 = slower
    style_l = (style or "").strip().lower()
    if length_scale is None:
        if style_l in {"singing", "song", "jingle", "music", "lyrics"}:
            length_scale = 1.18
        else:
            length_scale = 1.0
    try:
        length_scale = float(length_scale)
    except (TypeError, ValueError):
        length_scale = 1.0
    length_scale = max(0.7, min(1.6, length_scale))

    env = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"

    with _lock:
        with tempfile.TemporaryDirectory(prefix="hal_piper_") as tmp:
            out = Path(tmp) / "speech.wav"
            cmd = [str(exe), "--model", str(model), "--output_file", str(out)]
            if abs(length_scale - 1.0) > 0.01:
                cmd.extend(["--length_scale", f"{length_scale:.3f}"])
            try:
                proc = subprocess.run(
                    cmd,
                    input=speech.encode("utf-8"),
                    capture_output=True,
                    timeout=SYNTH_TIMEOUT_S,
                    env=env,
                    cwd=str(HAL_ROOT),
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"piper timed out after {SYNTH_TIMEOUT_S}s") from exc

            if proc.returncode != 0 or not out.is_file() or out.stat().st_size < 44:
                err = (proc.stderr or b"").decode("utf-8", errors="replace")[:400]
                raise RuntimeError(f"piper failed rc={proc.returncode}: {err}")
            return out.read_bytes()
