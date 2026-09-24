"""Sync clean Docker build context for HAL Model Gateway (community pack).

Prefer the shipped ./context/. If HAL_ROOT (or a monorepo two levels up) contains
hal_model_gateway/, refresh the context from that tree.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import sys

BASE = Path(__file__).resolve().parent
CTX = BASE / "context"


def find_root() -> Path | None:
    env = os.environ.get("HAL_ROOT")
    if env:
        p = Path(env)
        if (p / "hal_model_gateway" / "server.py").exists():
            return p
    cand = BASE.parent.parent
    if (cand / "hal_model_gateway" / "server.py").exists():
        return cand
    return None


def scrub_peers(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        dst.write_text('{"version": 1, "peers": []}\n', encoding="utf-8")
        return
    data = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for peer in data.get("peers") or []:
            if isinstance(peer, dict):
                for k in list(peer.keys()):
                    if any(x in k.lower() for x in ("token", "secret", "key", "password")):
                        peer[k] = "<set-via-env>"
    dst.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ensure_entrypoint_lf() -> None:
    ep = CTX / "docker-entrypoint.sh"
    if ep.exists():
        text = ep.read_text(encoding="utf-8").replace("\r\n", "\n")
        ep.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    root = find_root()
    if root is None:
        if not (CTX / "hal_model_gateway" / "server.py").exists():
            print("No HAL_ROOT monorepo found and ./context is incomplete.", file=sys.stderr)
            print("Set HAL_ROOT to your HAL tree, or keep the shipped context/ intact.", file=sys.stderr)
            return 1
        for name in ("Dockerfile", "docker-entrypoint.sh", "requirements.txt", ".dockerignore"):
            src = BASE / name
            if src.exists():
                shutil.copy2(src, CTX / name)
        ensure_entrypoint_lf()
        print("Using shipped context:", CTX)
        return 0

    dest = CTX / "hal_model_gateway"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "providers").mkdir()
    (dest / "contracts").mkdir()
    src_pkg = root / "hal_model_gateway"
    for name in [
        "__init__.py", "server.py", "registry.py", "router.py",
        "web_search.py", "image_gen.py", "run_code.py",
        "piper_tts.py", "whisper_stt.py",
    ]:
        shutil.copy2(src_pkg / name, dest / name)
    shutil.copy2(src_pkg / "providers" / "__init__.py", dest / "providers" / "__init__.py")
    shutil.copy2(src_pkg / "contracts" / "__init__.py", dest / "contracts" / "__init__.py")

    oc_dst = CTX / "opencode_config.json"
    if not oc_dst.exists() and (root / "opencode_config.json").exists():
        shutil.copy2(root / "opencode_config.json", oc_dst)

    scrub_peers(root / "config" / "peers.json", CTX / "config" / "peers.json")

    for name in ("requirements.txt", "docker-entrypoint.sh", "Dockerfile", ".dockerignore"):
        src = BASE / name
        if name == "requirements.txt" and not src.exists():
            alt = src_pkg / "requirements.txt"
            if alt.exists():
                shutil.copy2(alt, CTX / name)
            continue
        if src.exists():
            shutil.copy2(src, CTX / name)

    ensure_entrypoint_lf()
    print("Synced from", root)
    print("Files:", sorted(p.name for p in dest.rglob("*") if p.is_file()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
