"""
HAL free image generation for the public Model Gateway.

Backends (in order):
  1) Local SDXL (diffusers) when enough free VRAM
  2) Cloudflare Workers AI @cf/stabilityai/stable-diffusion-xl-base-1.0 ($0.00/step)
  3) Tiny PIL placeholder (last resort)

Saves PNG under /app/data/gateway_images/ and returns a public
markdown URL served by GET /v1/images/{id}.png on the gateway (api.halsupreme.com).
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("hal.image_gen")

GENERATE_IMAGE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Generate an image from a text prompt (FREE local SDXL or Workers AI). "
            "Use when the user asks to draw, generate, create, paint, or visualize an image, "
            "logo, illustration, scene, or artwork. Returns a public HTTPS URL — "
            "ALWAYS include BOTH: (1) markdown ![description](url) with the URL unbroken (never insert spaces/newlines inside the URL), and (2) a plain line Generated image: followed by the same URL on the next line."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed text description of the image to generate",
                },
                "size": {
                    "type": "string",
                    "description": "Optional size WxH. Default 768x768 (VRAM-friendly). Allowed: 512x512, 768x768, 1024x1024, 1024x576, 576x1024.",
                    "default": "768x768",
                },
            },
            "required": ["prompt"],
        },
    },
}

_IMAGE_DIR = Path(
    os.environ.get(
        "HAL_GATEWAY_IMAGE_DIR",
        str(Path(__file__).resolve().parents[1] / "data" / "gateway_images"),
    )
)
_PUBLIC_BASE = os.environ.get("HAL_PUBLIC_API_BASE", "https://api.halsupreme.com").rstrip("/")
_WORKERS_AI_URL = os.environ.get(
    "HAL_WORKERS_AI_IMAGE_URL",
    "https://hal-chat.therealjakobhedrich.workers.dev/v1/images/generate",
)
_HF_HOME = os.environ.get("HF_HOME", r"D:\AI_Cache\huggingface")
_SDXL_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
_DEFAULT_SIZE = (768, 768)
_ALLOWED_SIZES = {
    (512, 512),
    (768, 768),
    (1024, 1024),
    (1024, 576),
    (576, 1024),
}
_LOCAL_TIMEOUT_S = float(os.environ.get("HAL_IMAGE_LOCAL_TIMEOUT_S", "180"))
_MIN_FREE_VRAM_MB = float(os.environ.get("HAL_IMAGE_MIN_FREE_VRAM_MB", "3500"))
_GEN_LOCK = threading.Lock()
_pipe = None
_pipe_lock = threading.Lock()

_IMAGE_HINT_RE = re.compile(
    r"\b("
    r"generate\s+(an?\s+)?image|draw\s+(an?\s+)?|create\s+(an?\s+)?(image|picture|illustration|logo|art)|"
    r"paint\s+(an?\s+)?|make\s+(an?\s+)?(image|picture|illustration|logo|art)|"
    r"text[\s-]to[\s-]image|txt2img|imagine\s+(an?\s+)?|"
    r"visualize|visualise|render\s+(an?\s+)?(image|picture|scene)|"
    r"illustration\s+of|picture\s+of|artwork\s+of"
    r")\b",
    re.I,
)


def message_needs_image(text: str) -> bool:
    """Heuristic for fast path — only burn GPU when clearly asked."""
    if not text:
        return False
    return bool(_IMAGE_HINT_RE.search(text))


def _parse_size(size: Any) -> tuple[int, int]:
    if not size:
        return _DEFAULT_SIZE
    s = str(size).lower().strip().replace(" ", "")
    m = re.match(r"^(\d{3,4})x(\d{3,4})$", s)
    if not m:
        return _DEFAULT_SIZE
    w, h = int(m.group(1)), int(m.group(2))
    # Snap to nearest allowed
    if (w, h) in _ALLOWED_SIZES:
        return w, h
    # Prefer square 768 if weird
    return _DEFAULT_SIZE


def _public_url(image_id: str) -> str:
    return f"{_PUBLIC_BASE}/v1/images/{image_id}.png"


def _save_png_bytes(data: bytes, image_id: Optional[str] = None) -> tuple[str, Path]:
    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    iid = image_id or uuid.uuid4().hex
    path = _IMAGE_DIR / f"{iid}.png"
    path.write_bytes(data)
    return iid, path


def _free_vram_mb() -> float:
    try:
        import torch
        if not torch.cuda.is_available():
            return 0.0
        free, _total = torch.cuda.mem_get_info()
        return free / (1024 * 1024)
    except Exception:
        return 0.0


def _load_local_pipe():
    global _pipe
    with _pipe_lock:
        if _pipe is not None:
            return _pipe
        import torch
        from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler

        os.environ.setdefault("HF_HOME", _HF_HOME)
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        logger.info("Loading local SDXL (first call may take a while)...")
        snap_root = Path(_HF_HOME) / "hub" / "models--stabilityai--stable-diffusion-xl-base-1.0" / "snapshots"
        model_path = _SDXL_MODEL
        if snap_root.is_dir():
            snaps = sorted([d for d in snap_root.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True)
            if snaps:
                model_path = str(snaps[0])
                logger.info("Using local SDXL snapshot %s", model_path)
        pipe = StableDiffusionXLPipeline.from_pretrained(
            model_path,
            torch_dtype=dtype,
            local_files_only=True,
        )
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
        if torch.cuda.is_available():
            pipe = pipe.to("cuda")
            try:
                pipe.enable_attention_slicing()
            except Exception:
                pass
            try:
                pipe.enable_vae_slicing()
            except Exception:
                pass
        _pipe = pipe
        logger.info("Local SDXL ready")
        return _pipe


def _generate_local(prompt: str, width: int, height: int) -> bytes:
    import torch

    free = _free_vram_mb()
    if free < _MIN_FREE_VRAM_MB:
        raise RuntimeError(f"insufficient free VRAM ({free:.0f} MB < {_MIN_FREE_VRAM_MB:.0f} MB)")

    pipe = _load_local_pipe()
    negative = (
        "low quality, blurry, distorted, deformed, ugly, text, watermark, "
        "signature, jpeg artifacts, worst quality, low resolution"
    )
    with torch.inference_mode():
        result = pipe(
            prompt=prompt,
            negative_prompt=negative,
            num_inference_steps=20,
            guidance_scale=7.0,
            width=width,
            height=height,
        )
    img = result.images[0]
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _gateway_token() -> str:
    configured = str(os.environ.get("HAL_GATEWAY_TOKEN") or "").strip()
    if configured:
        return configured
    token_file = Path(
        os.environ.get(
            "HAL_GATEWAY_TOKEN_FILE",
            str(Path(__file__).resolve().parents[1] / "data" / "model_gateway.token"),
        )
    )
    try:
        return token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _generate_workers_ai(prompt: str, width: int, height: int) -> bytes:
    """Call hal-chat Worker AI binding endpoint (FREE SDXL, $0.00/step)."""
    import urllib.request

    token = _gateway_token()
    if not token:
        raise RuntimeError("gateway token unavailable for Workers AI fallback")
    # Cap Workers AI size — model docs allow up to 2048 but keep modest
    w = min(width, 1024)
    h = min(height, 1024)
    payload = json.dumps(
        {
            "prompt": prompt,
            "width": w,
            "height": h,
            "num_steps": 15,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _WORKERS_AI_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "image/png",
            "User-Agent": "HAL-Supreme-Gateway/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        data = resp.read()
        if "application/json" in ctype:
            err = data.decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Workers AI error: {err}")
        if not data or len(data) < 100:
            raise RuntimeError("Workers AI returned empty image")
        return data


def _generate_pil_placeholder(prompt: str, width: int, height: int) -> bytes:
    """Last-resort FREE CPU placeholder so the tool never hard-fails silently."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), (8, 10, 18))
    draw = ImageDraw.Draw(img)
    # HAL eye-ish glow
    cx, cy = width // 2, height // 2
    for r, col in (
        (min(width, height) // 3, (20, 40, 80)),
        (min(width, height) // 5, (40, 90, 160)),
        (min(width, height) // 10, (120, 200, 255)),
        (min(width, height) // 22, (220, 240, 255)),
    ):
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
    label = "HAL image (placeholder)"
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    text = (prompt or "")[:80]
    draw.text((16, 16), label, fill=(180, 200, 220), font=font)
    draw.text((16, height - 36), text, fill=(140, 160, 180), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_image(prompt: str, size: Any = None) -> dict[str, Any]:
    """
    Generate an image and return a result dict with public URL + markdown.
    Thread-safe; timeouts/OOM fall through backends.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt is required"}
    if len(prompt) > 2000:
        prompt = prompt[:2000]
    width, height = _parse_size(size)
    errors: list[str] = []
    # Workers AI SDXL unit pricing is FREE (0 dollars per step). Prefer it for public chat.
    # Local SDXL is fallback when Workers AI fails and enough VRAM is free.
    backends = [
        ("workers_ai", _generate_workers_ai),
        ("local_sdxl", _generate_local),
        ("pil_placeholder", _generate_pil_placeholder),
    ]

    with _GEN_LOCK:
        for name, fn in backends:
            try:
                t0 = time.time()
                if name == "local_sdxl":
                    # Soft timeout via wall clock check after (diffusers has no cancel)
                    data = fn(prompt, width, height)
                    if time.time() - t0 > _LOCAL_TIMEOUT_S:
                        errors.append(f"{name}: exceeded {_LOCAL_TIMEOUT_S:.0f}s")
                        continue
                else:
                    data = fn(prompt, width, height)
                image_id, path = _save_png_bytes(data)
                url = _public_url(image_id)
                md = f"![{_safe_alt(prompt)}]({url})"
                short = f"Generated image:\n{url}"
                elapsed = round(time.time() - t0, 2)
                logger.info(
                    "image ok backend=%s id=%s %dx%d %.2fs path=%s",
                    name, image_id, width, height, elapsed, path,
                )
                return {
                    "ok": True,
                    "url": url,
                    "markdown": md,
                    "display": short,
                    "backend": name,
                    "width": width,
                    "height": height,
                    "prompt": prompt,
                    "elapsed_s": elapsed,
                    "image_id": image_id,
                    "note": (
                        "Include BOTH of these in your reply exactly once, character-for-character. "
                        "NEVER insert spaces, newlines, or soft breaks inside the URL:\n"
                        f"{md}\n\n{short}"
                        + ("\n(CPU placeholder — GPU was busy.)" if name == "pil_placeholder" else "")
                    ),
                }
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                errors.append(f"{name}: {msg}")
                logger.warning("image backend %s failed: %s", name, msg)
                # Free CUDA cache between attempts
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass

    return {
        "ok": False,
        "error": "All image backends failed",
        "details": errors[:6],
    }


def _safe_alt(prompt: str) -> str:
    alt = re.sub(r"[\[\]\(\)\n\r]+", " ", prompt).strip()
    if len(alt) > 80:
        alt = alt[:77] + "..."
    return alt or "generated image"


def image_file_path(image_id: str) -> Optional[Path]:
    """Resolve a safe image id to a path under the image dir."""
    iid = (image_id or "").strip().lower()
    if iid.endswith(".png"):
        iid = iid[:-4]
    if not re.fullmatch(r"[a-f0-9]{8,64}", iid):
        return None
    path = (_IMAGE_DIR / f"{iid}.png").resolve()
    try:
        path.relative_to(_IMAGE_DIR.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


def execute_generate_image(arguments: Any) -> str:
    args = arguments
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {"prompt": args}
    if not isinstance(args, dict):
        args = {}
    prompt = str(args.get("prompt") or args.get("query") or "").strip()
    size = args.get("size") or args.get("dimensions")
    result = generate_image(prompt, size)
    return json.dumps(result, ensure_ascii=False)


def generate_image_tool_result(prompt: str, size: Any = None) -> str:
    return json.dumps(generate_image(prompt, size), ensure_ascii=False)
