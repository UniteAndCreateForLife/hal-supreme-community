"""
HAL free local code sandbox for the Model Gateway.

Runs short Python (and optional Node) snippets in a fresh temp directory via
subprocess argv list (never shell=True with user strings). Hard wall-clock
timeout, truncated I/O, light pattern refusals.

Security model (honest, not bulletproof):
  - $0: no Cloudflare Containers / paid sandbox APIs
  - Timeout kills the process tree (best-effort on Windows)
  - cwd = ephemeral temp dir, deleted after
  - No shell=True; code written to a file and invoked with fixed argv
  - Light deny-list of dangerous patterns (not perfect security)
  - Network is NOT fully blocked on Windows; treat as semi-trusted local run
  - Memory limits are best-effort only (OS may still OOM-kill)
  - Public chat reaches this only through the authenticated edge worker

Returns JSON: {stdout, stderr, exit_code, language, timed_out?, refused?}
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("hal.run_code")

MAX_CODE_BYTES = 12_000
DEFAULT_TIMEOUT_S = float(os.environ.get("HAL_RUN_CODE_TIMEOUT_S", "10"))
MAX_TIMEOUT_S = 12.0
MIN_TIMEOUT_S = 2.0
MAX_OUTPUT_CHARS = 8_000

RUN_CODE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_code",
        "description": (
            "Run a short code snippet in HAL's FREE local sandbox on the gateway host. "
            "Use to verify Python (preferred) or JavaScript one-liners / small programs, "
            "check outputs, or debug. Returns stdout/stderr/exit_code. "
            "Do NOT use for long jobs, network calls, file system exploration, or secrets. "
            "After success, report the actual stdout (e.g. print results) clearly to the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "Language: python (default) or javascript/node",
                    "enum": ["python", "python3", "py", "javascript", "js", "node"],
                    "default": "python",
                },
                "code": {
                    "type": "string",
                    "description": "Source code to execute (max ~12KB)",
                },
                "timeout_s": {
                    "type": "number",
                    "description": "Wall-clock timeout seconds (2-12, default 10)",
                    "default": 10,
                },
            },
            "required": ["code"],
        },
    },
}

# Light refusals — NOT a security boundary; just reduces footguns.
_DENY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bos\.system\s*\(", re.I), "os.system"),
    (re.compile(r"\bsubprocess\.(?:call|run|Popen|check_output|check_call)\s*\(", re.I), "subprocess"),
    (re.compile(r"\b(?:eval|exec)\s*\(\s*(?:input|open|__import__)", re.I), "dynamic eval/exec of external"),
    (re.compile(r"\b__import__\s*\(\s*['\"]ctypes['\"]", re.I), "ctypes"),
    (re.compile(r"\bimport\s+ctypes\b|\bfrom\s+ctypes\b", re.I), "ctypes"),
    (re.compile(r"\bimport\s+win32|from\s+win32", re.I), "win32"),
    (re.compile(r"\bshutil\.rmtree\s*\(", re.I), "shutil.rmtree"),
    (re.compile(r"\bos\.(?:remove|unlink|rmdir|removedirs)\s*\(", re.I), "os remove"),
    (re.compile(r"\b(?:rm\s+-rf|del\s+/[sf]|format\s+[a-z]:)", re.I), "destructive shell"),
    (re.compile(r"\b(?:powershell|cmd\.exe|Start-Process)\b", re.I), "shell invoke"),
    (re.compile(r"\bopen\s*\(\s*['\"][a-zA-Z]:\\", re.I), "absolute path open"),
    (re.compile(r"\bopen\s*\(\s*['\"]/(?:etc|root|home|Users|Windows)", re.I), "sensitive path open"),
    (re.compile(r"child_process|\brequire\s*\(\s*['\"]net['\"]|\brequire\s*\(\s*['\"]fs['\"]", re.I), "node system module"),
    (re.compile(r"\brequire\s*\(\s*['\"]child_process['\"]", re.I), "child_process"),
]

_CODE_HINT_RE = re.compile(
    r"\b("
    r"run\s+(this\s+)?(code|python|script|snippet|program)|"
    r"execute\s+(this\s+)?(code|python|script)|"
    r"eval(uate)?\s+(this\s+)?(code|expression)|"
    r"print\s+2\s*\+\s*2|"
    r"one[\s-]?liner|"
    r"verify\s+(the\s+)?(output|result|code)|"
    r"sandbox|"
    r"```(?:python|py|javascript|js)\b"
    r")\b",
    re.I,
)


def message_needs_code(text: str) -> bool:
    """Heuristic for Fast mode — only offer run_code on clear run-this-code asks."""
    if not text:
        return False
    return bool(_CODE_HINT_RE.search(text))


def _normalize_language(lang: Any) -> str:
    s = str(lang or "python").strip().lower()
    if s in {"python", "python3", "py", "py3"}:
        return "python"
    if s in {"javascript", "js", "node", "nodejs"}:
        return "javascript"
    return "python"


def _clamp_timeout(v: Any) -> float:
    try:
        t = float(v)
    except (TypeError, ValueError):
        t = DEFAULT_TIMEOUT_S
    return max(MIN_TIMEOUT_S, min(MAX_TIMEOUT_S, t))


def _refuse_dangerous(code: str) -> Optional[str]:
    for pat, label in _DENY_PATTERNS:
        if pat.search(code):
            return f"refused: pattern resembling {label}"
    return None


def _find_python() -> Optional[list[str]]:
    # Prefer the interpreter running the gateway.
    if sys.executable:
        return [sys.executable]
    for name in ("python3", "python", "py"):
        path = shutil.which(name)
        if path:
            if name == "py":
                return [path, "-3"]
            return [path]
    return None


def _find_node() -> Optional[list[str]]:
    path = shutil.which("node")
    if path:
        return [path]
    return None


def _truncate(s: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 20] + "\n...[truncated]..."


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # /T = tree, /F = force
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_code(
    code: str,
    language: str = "python",
    timeout_s: Any = None,
) -> dict[str, Any]:
    """
    Execute code in a fresh temp dir. Always returns a result dict (never raises
    for user code failures).
    """
    lang = _normalize_language(language)
    src = code if isinstance(code, str) else str(code or "")
    if not src.strip():
        return {
            "stdout": "",
            "stderr": "code is required",
            "exit_code": 1,
            "language": lang,
            "refused": True,
        }
    raw_bytes = src.encode("utf-8", errors="replace")
    if len(raw_bytes) > MAX_CODE_BYTES:
        return {
            "stdout": "",
            "stderr": f"code too long ({len(raw_bytes)} bytes; max {MAX_CODE_BYTES})",
            "exit_code": 1,
            "language": lang,
            "refused": True,
        }

    denied = _refuse_dangerous(src)
    if denied:
        return {
            "stdout": "",
            "stderr": denied,
            "exit_code": 1,
            "language": lang,
            "refused": True,
        }

    timeout = _clamp_timeout(timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S)

    if lang == "python":
        argv_base = _find_python()
        if not argv_base:
            return {
                "stdout": "",
                "stderr": "python interpreter not found on gateway host",
                "exit_code": 127,
                "language": lang,
            }
        filename = "main.py"
    else:
        argv_base = _find_node()
        if not argv_base:
            return {
                "stdout": "",
                "stderr": "node interpreter not found on gateway host",
                "exit_code": 127,
                "language": lang,
            }
        filename = "main.js"

    tmp: Optional[str] = None
    proc: Optional[subprocess.Popen] = None
    timed_out = False
    try:
        tmp = tempfile.mkdtemp(prefix="hal_sandbox_")
        script_path = Path(tmp) / filename
        script_path.write_text(src, encoding="utf-8", newline="\n")
        argv = list(argv_base) + [str(script_path)]

        # Minimal env — keep PATH for interpreter DLLs on Windows, drop secrets.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "WINDIR": os.environ.get("WINDIR", ""),
            "TEMP": tmp,
            "TMP": tmp,
            "TMPDIR": tmp,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_COLOR": "1",
            "HOME": tmp,
            "USERPROFILE": tmp,
        }
        # Drop empty values
        env = {k: v for k, v in env.items() if v}

        creationflags = 0
        if os.name == "nt":
            # Hide console window for the child
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        t0 = time.time()
        proc = subprocess.Popen(
            argv,
            cwd=tmp,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=env,
            shell=False,
            creationflags=creationflags,
        )
        try:
            out_b, err_b = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc)
            try:
                out_b, err_b = proc.communicate(timeout=3)
            except Exception:
                out_b, err_b = b"", b""
        elapsed = round(time.time() - t0, 3)
        stdout = _truncate((out_b or b"").decode("utf-8", errors="replace"))
        stderr = _truncate((err_b or b"").decode("utf-8", errors="replace"))
        if timed_out:
            note = f"timed out after {timeout:.0f}s"
            stderr = (stderr + ("\n" if stderr else "") + note).strip()
            exit_code = 124
        else:
            exit_code = int(proc.returncode if proc.returncode is not None else 1)

        result = {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "language": lang,
            "elapsed_s": elapsed,
            "timed_out": timed_out,
            "note": (
                "Local HAL sandbox ($0). Network not fully blocked on Windows. "
                "Show stdout to the user when reporting results."
            ),
        }
        logger.info(
            "run_code lang=%s exit=%s timed_out=%s elapsed=%.3fs code_bytes=%d",
            lang,
            exit_code,
            timed_out,
            elapsed,
            len(raw_bytes),
        )
        return result
    except Exception as exc:
        logger.warning("run_code failed: %s", exc)
        return {
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "exit_code": 1,
            "language": lang,
        }
    finally:
        if proc is not None and proc.poll() is None:
            _kill_process_tree(proc)
        if tmp:
            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass


def execute_run_code(arguments: Any) -> str:
    args = arguments
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {"code": args}
    if not isinstance(args, dict):
        args = {}
    code = str(args.get("code") or args.get("source") or args.get("script") or "")
    language = args.get("language") or args.get("lang") or "python"
    timeout_s = args.get("timeout_s", args.get("timeout"))
    return json.dumps(run_code(code, language, timeout_s), ensure_ascii=False)


def format_code_context(result: dict[str, Any]) -> str:
    """Human-readable block for local/fast heuristic injection."""
    lines = [
        "[HAL local sandbox run_code result]",
        f"language={result.get('language')} exit_code={result.get('exit_code')} "
        f"timed_out={result.get('timed_out', False)}",
    ]
    out = (result.get("stdout") or "").strip()
    err = (result.get("stderr") or "").strip()
    if out:
        lines.append("stdout:")
        lines.append(out)
    if err:
        lines.append("stderr:")
        lines.append(err)
    lines.append(
        "Report the actual stdout/stderr to the user. Do not invent different output."
    )
    return "\n".join(lines)
