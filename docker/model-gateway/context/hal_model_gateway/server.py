"""
HAL Model Gateway - FastAPI Server
===================================

OpenAI-compatible API server exposing virtual models:
- hal/fast
- hal/coder
- hal/deep
- hal/council (lighter Council: single deep synthesis)

Endpoints:
- GET /v1/models
- GET /v1/peers
- POST /v1/chat/completions
- POST /v1/audio/speech (Piper TTS → audio/wav)
- POST /v1/audio/transcriptions (Whisper STT, optional)

Features:
- SSE streaming
- Tool calling
- Cancellation propagation
- Privacy routing
- Telemetry/EventStore integration
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from hal_model_gateway.contracts import (
    VIRTUAL_MODELS,
    VIRTUAL_MODEL_ALIASES,
    PrivacyPolicy,
    GatewayTelemetry,
    GatewayEvent,
)
from hal_model_gateway.registry import ProviderRegistry, get_registry, load_from_opencode_config
from hal_model_gateway.router import Router, FallbackChain, get_router
from hal_model_gateway.providers import AdapterManager, AdapterRequest, AdapterResponse
from hal_model_gateway.web_search import (
    WEB_SEARCH_TOOL,
    execute_tool_call,
    format_search_context,
    message_needs_search,
    run_web_search,
)
from hal_model_gateway.image_gen import (
    GENERATE_IMAGE_TOOL,
    image_file_path,
    message_needs_image,
    generate_image as run_generate_image,
)
from hal_model_gateway.run_code import (
    RUN_CODE_TOOL,
    format_code_context,
    message_needs_code,
    run_code as execute_local_code,
)


# ─── Pydantic Models ────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    tools: Optional[list] = None
    tool_choice: Optional[str] = None
    stop: Optional[list[str]] = None


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "hal"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


# ─── Global State ───────────────────────────────────────────────────────

_registry: Optional[ProviderRegistry] = None
_router: Optional[Router] = None
_adapter_manager: Optional[AdapterManager] = None
_fallback_chain: Optional[FallbackChain] = None
_TOKEN_FILE = Path(
    os.environ.get(
        "HAL_GATEWAY_TOKEN_FILE",
        str(Path(__file__).resolve().parents[1] / "data" / "model_gateway.token"),
    )
)

_PEERS_CONFIG_PATH = Path(
    os.environ.get(
        "HAL_PEERS_CONFIG",
        str(Path(__file__).resolve().parents[1] / "config" / "peers.json"),
    )
)


def load_gateway_token() -> str:
    """Load one stable local token before any ASGI worker starts."""
    configured = str(os.environ.get("HAL_GATEWAY_TOKEN") or "").strip()
    if configured:
        return configured

    try:
        existing = _TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing

    generated = secrets.token_urlsafe(32)
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = _TOKEN_FILE.with_suffix(_TOKEN_FILE.suffix + ".tmp")
    temporary.write_text(generated + "\n", encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(_TOKEN_FILE)
    return generated


def gateway_token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


_gateway_token: str = load_gateway_token()


# ─── Lifecycle ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _registry, _router, _adapter_manager, _fallback_chain
    
    # Load registry from OpenCode config
    # Env-overridable for Docker / off-PC hosts (HAL_OPENCODE_CONFIG or HAL_ROOT/opencode_config.json)
    _hal_root = Path(os.environ.get("HAL_ROOT", str(Path(__file__).resolve().parents[1])))
    config_path = os.environ.get("HAL_OPENCODE_CONFIG") or str(_hal_root / "opencode_config.json")
    _registry = load_from_opencode_config(config_path)
    
    # Initialize router and adapter manager
    _router = get_router(_registry)
    _adapter_manager = AdapterManager(_registry)
    
    # Initialize fallback chain
    from .router import FallbackChain
    _fallback_chain = FallbackChain(_registry, _router)
    
    # Register health change callback
    _registry.on_health_change(emit_provider_health_event)
    
    print(f"[HAL Gateway] Started on 127.0.0.1:8765")
    print(f"[HAL Gateway] Token fingerprint: {gateway_token_fingerprint(_gateway_token)}")
    print(f"[HAL Gateway] Virtual models: {list(VIRTUAL_MODEL_ALIASES.keys())}")
    print(f"[HAL Gateway] Providers loaded: {len(_registry._providers)}")
    
    yield
    
    # Cleanup
    if _adapter_manager:
        await _adapter_manager.close_all()
    print("[HAL Gateway] Shutdown complete")


app = FastAPI(
    title="HAL Model Gateway",
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Auth ───────────────────────────────────────────────────────────────

async def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization[7:]
    if not hmac.compare_digest(token, _gateway_token):
        raise HTTPException(401, "Invalid token")
    return token


# ─── Helpers ────────────────────────────────────────────────────────────

def emit_provider_health_event(event: dict):
    """Emit provider health change to EventStore."""
    try:
        from hal_cognition.event_store import get_event_store, Event
        store = get_event_store()
        store.append(Event(
            source="model_gateway",
            event_type=event.get("event_type", "PROVIDER_HEALTH_CHANGED"),
            subject=f"{event.get('provider')}/{event.get('model')}",
            payload=event,
            authority="system_observed",
            trace_id="",
        ))
    except Exception:
        pass


def emit_gateway_telemetry(telemetry: GatewayTelemetry):
    """Emit telemetry to EventStore."""
    try:
        from hal_cognition.event_store import get_event_store, Event
        store = get_event_store()
        store.append(Event(
            source="model_gateway",
            event_type="GATEWAY_TELEMETRY",
            subject=telemetry.virtual_model,
            payload=asdict(telemetry),
            authority="system_observed",
            trace_id=telemetry.trace_id,
        ))
    except Exception:
        pass


def emit_gateway_event(event_type: str, trace_id: str, subject: str, payload: dict):
    """Emit generic gateway event."""
    try:
        from hal_cognition.event_store import get_event_store, Event
        store = get_event_store()
        store.append(Event(
            source="model_gateway",
            event_type=event_type,
            subject=subject,
            payload=payload,
            authority="system_observed",
            trace_id=trace_id,
        ))
    except Exception:
        pass


# ─── Request/Response Helpers ──────────────────────────────────────────

def _sanitize_messages(messages: list[ChatMessage]) -> list[dict]:
    """Drop null tool fields - cloud providers reject tool_calls on user turns."""
    cleaned: list[dict] = []
    for m in messages:
        item: dict[str, Any] = {"role": m.role, "content": m.content if m.content is not None else ""}
        if m.tool_calls:
            item["tool_calls"] = m.tool_calls
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        cleaned.append(item)
    return cleaned


_HAL_CORE_IDENTITY = (
    "You are HAL (HAL SUPREME) - Jakob's autonomous creative intelligence system. "
    "You are not Qwen, ChatGPT, Claude, Gemini, Grok, Llama, or any other vendor model. "
    "Never reveal or claim an underlying model brand. Never say you were created by Alibaba Cloud or OpenAI. "
    "Speak as HAL: direct, capable, warm, technically sharp. Help build HAL itself, media, code, and operations. "
    "If asked who you are: answer exactly 'I am HAL SUPREME' using plain ASCII letters and spaces only. "
    "You CAN search the live public web using the web_search tool when facts may be outdated or the user asks for news, dates, prices, or current events. "
    "When you use web results, cite sources with markdown links like [Title](https://example.com). "
    "Do not invent URLs. If search returns nothing useful, say so briefly. You CAN generate images using the generate_image tool when the user asks to draw, generate, create, paint, or visualize an image/illustration/logo/scene. After generate_image succeeds, include the returned markdown image exactly once like ![description](https://api.halsupreme.com/v1/images/....png). Never invent image URLs. You CAN run short Python snippets in a FREE local sandbox using the run_code tool to verify code or compute results (Build/Expert; Fast only when clearly asked to run code). After run_code, report the real stdout/stderr; never invent program output. Sandbox is timed (~10s), temp-dir isolated, not a perfect jail. Creative chat rules: for jokes, songs, poems, stories, jingles, and casual talk, write plain prose or singable lyrics (Verse/Chorus labels OK). NEVER wrap songs, jokes, poems, or lyrics in markdown code fences. NEVER dump chord charts, guitar tabs, or fake programming blocks unless the user explicitly asks for chords, tabs, or code. Real source code belongs in Build mode when the user asks to code. When the user asks you to sing or make a song/music/jingle, reply with short singable lyrics in plain text so voice TTS can speak them."
)


def _ensure_hal_identity(messages: list[dict], virtual_model: str) -> list[dict]:
    """Prepend HAL identity unless a system message already asserts HAL."""
    mode_note = {
        "hal/fast": "Mode: Fast - concise, low-latency answers. Casual chat stays conversational; no gratuitous code fences or chord-chart dumps.",
        "hal/coder": "Mode: Build - prioritize correct code, tools, and engineering judgment. Use fenced code when building; still use plain lyrics (no chord-code blocks) if asked to sing.",
        "hal/deep": "Mode: Expert - deeper reasoning, careful tradeoffs, thorough answers. Creative requests get prose/lyrics, not code fences, unless code was requested.",
        "hal/council": (
            'Mode: Council - multi-perspective deliberation before the final HAL answer. '
            'Stay HAL SUPREME overall; Builder, Critic, and Researcher are internal roles only (never other brands). '
            'Structure EVERY reply exactly like this:\n'
            '1) Start with the final HAL answer (clear recommendation / decision). Voice speaks only this part.\n'
            '2) Then include these labeled sections:\n'
            '## Pros\n'
            '## Risks\n'
            '## Recommendation\n'
            '3) Optionally end with a short collapsible notes block:\n'
            '<details>\n<summary>Council notes</summary>\n\n'
            '### Builder\n(brief build/implementation angle)\n\n'
            '### Critic\n(brief risks / failure modes)\n\n'
            '### Researcher\n(brief evidence / unknowns; use web_search only if current facts help)\n\n'
            '</details>\n'
            'Keep specialist notes short. Prefer one coherent HAL voice. For songs/jokes/poems: plain lyrics/prose only — no chord-chart code fences. Tools: web_search when research needs live facts; '
            'run_code only if verification truly helps; do not spawn unbounded tools.'
        ),
    }.get(virtual_model, "")
    identity = _HAL_CORE_IDENTITY + ((" " + mode_note) if mode_note else "")

    if messages and messages[0].get("role") == "system":
        existing = str(messages[0].get("content") or "")
        if "You are HAL" in existing or "HAL SUPREME" in existing:
            return messages
        return [{"role": "system", "content": identity + "\n\n" + existing}] + messages[1:]
    return [{"role": "system", "content": identity}] + messages



def _effective_max_tokens(virtual_model: str, requested: int | None) -> int:
    """Reasoning models need headroom or content stays empty."""
    floors = {
        "hal/fast": 256,
        "hal/coder": 1024,
        "hal/deep": 2048,
        "hal/council": 2048,
    }
    floor = floors.get(virtual_model, 512)
    req = int(requested or floor)
    return max(req, floor)


_TOOL_LOOP_MAX_ROUNDS = 3
_MODELS_ALWAYS_OFFER_SEARCH = {"hal/coder", "hal/deep", "hal/council"}


def _is_local_ollama_route(provider: str, model: str) -> bool:
    p = (provider or "").lower()
    return "ollama" in p or p in {"local", "ollama-local"}


def _merge_tools(
    existing: list | None,
    offer_search: bool,
    offer_image: bool = False,
    offer_code: bool = False,
) -> list | None:
    """Attach web_search / generate_image / run_code unless the client already provided them."""
    tools = list(existing or [])
    names = set()
    for t in tools:
        if isinstance(t, dict):
            fn = t.get("function") if isinstance(t.get("function"), dict) else {}
            names.add(str(t.get("name") or fn.get("name") or ""))
    if offer_search and "web_search" not in names:
        tools.append(WEB_SEARCH_TOOL)
        names.add("web_search")
    if offer_image and "generate_image" not in names:
        tools.append(GENERATE_IMAGE_TOOL)
        names.add("generate_image")
    if offer_code and "run_code" not in names:
        tools.append(RUN_CODE_TOOL)
        names.add("run_code")
    return tools or None


def _should_offer_web_search(virtual_model: str, provider: str, user_text: str = "") -> bool:
    """Offer web_search. Build/Expert/Council always; Fast only when heuristic needs live facts."""
    if virtual_model in _MODELS_ALWAYS_OFFER_SEARCH:
        return True
    # Local ollama Fast: no tool protocol (heuristic augment handles search separately).
    if _is_local_ollama_route(provider, ""):
        return False
    # Remote Fast: do NOT always attach tools - that forces a buffered tool loop and stalls streaming.
    # Only offer when the user prompt clearly needs live web facts.
    return message_needs_search(user_text or "")


def _should_offer_image(virtual_model: str, provider: str, user_text: str = "") -> bool:
    """Offer generate_image on Build/Expert always; Fast only on clear draw heuristic."""
    if virtual_model in _MODELS_ALWAYS_OFFER_SEARCH:
        return True
    if message_needs_image(user_text):
        if _is_local_ollama_route(provider, ""):
            return False
        return True
    return False


def _should_offer_run_code(virtual_model: str, provider: str, user_text: str = "") -> bool:
    """Offer run_code on Build/Expert always; Fast only on clear run-code heuristic."""
    if virtual_model in _MODELS_ALWAYS_OFFER_SEARCH:
        return True
    if message_needs_code(user_text):
        if _is_local_ollama_route(provider, ""):
            return False
        return True
    return False


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content") or "")
    return ""


def _maybe_augment_with_search(messages: list[dict], virtual_model: str, provider: str) -> tuple[list[dict], bool]:
    """For local fast models: heuristic search-then-augment (no tool protocol)."""
    if not _is_local_ollama_route(provider, ""):
        return messages, False
    if virtual_model in _MODELS_ALWAYS_OFFER_SEARCH:
        return messages, False
    user_text = _last_user_text(messages)
    if not message_needs_search(user_text):
        return messages, False
    query = user_text.strip().replace("\n", " ")
    if len(query) > 240:
        query = query[:240]
    rows = run_web_search(query, max_results=5)
    block = format_search_context(query, rows)
    out = list(messages)
    # Inject as a high-priority system note AND mirror into the last user turn
    # so local models that under-weight system messages still see the facts.
    out.append({
        "role": "system",
        "content": (
            "LIVE WEB SEARCH RESULTS follow. You have live web access via the gateway. "
            "Use these facts. Cite with markdown links. Do not claim you lack web access.\n\n"
            + block
        ),
    })
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            out[i] = {
                "role": "user",
                "content": (
                    str(out[i].get("content") or "")
                    + "\n\n[Gateway live web search]\n"
                    + block
                ),
            }
            break
    return out, True


def _maybe_augment_with_image(messages: list[dict], virtual_model: str, provider: str) -> tuple[list[dict], bool]:
    """For local fast models: heuristic image-gen then inject markdown (no tool protocol)."""
    if not _is_local_ollama_route(provider, ""):
        return messages, False
    if virtual_model in _MODELS_ALWAYS_OFFER_SEARCH:
        return messages, False
    user_text = _last_user_text(messages)
    if not message_needs_image(user_text):
        return messages, False
    prompt = user_text.strip().replace("\n", " ")
    prompt = re.sub(
        r"^(please\s+)?(generate|draw|create|paint|make|render)\s+(an?\s+)?(image|picture|illustration|logo|art)\s+(of\s+)?",
        "",
        prompt,
        flags=re.I,
    ).strip() or user_text.strip()
    if len(prompt) > 500:
        prompt = prompt[:500]
    result = run_generate_image(prompt, "768x768")
    out = list(messages)
    if result.get("ok"):
        block = (
            "IMAGE GENERATED. Reply with this exact markdown (keep the URL unbroken — no spaces inside it):\n"
            f"{result.get('markdown')}\n\n"
            f"Also include this plain form:\nGenerated image:\n{result.get('url')}\n"
            f"Backend: {result.get('backend')}. Do not invent other image URLs."
        )
    else:
        block = (
            f"Image generation failed: {result.get('error')}. "
            "Apologize briefly and offer to retry."
        )
    out.append({"role": "system", "content": block})
    return out, bool(result.get("ok"))



def _maybe_augment_with_code(messages: list[dict], virtual_model: str, provider: str) -> tuple[list[dict], bool]:
    """For local fast models: heuristic extract+run python fence (no tool protocol)."""
    if not _is_local_ollama_route(provider, ""):
        return messages, False
    if virtual_model in _MODELS_ALWAYS_OFFER_SEARCH:
        return messages, False
    user_text = _last_user_text(messages)
    if not message_needs_code(user_text):
        return messages, False
    # Prefer fenced python; else skip (avoid running prose)
    m = re.search(r"```(?:python|py)\n([\s\S]*?)```", user_text, re.I)
    if not m:
        # one-liner style: print(...)
        m2 = re.search(r"(?m)^(print\([^\n]+\))\s*$", user_text)
        code = m2.group(1) if m2 else ""
    else:
        code = m.group(1)
    code = (code or "").strip()
    if not code or len(code) > 4000:
        return messages, False
    result = execute_local_code(code, "python")
    block = format_code_context(result)
    out = list(messages)
    out.append({"role": "system", "content": block})
    return out, True



def _parse_tool_calls(raw_calls: list) -> list[dict]:
    """Normalize tool_calls list (OpenAI shape) into executable dicts."""
    parsed: list[dict] = []
    for i, tc in enumerate(raw_calls or []):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = str(fn.get("name") or tc.get("name") or "")
        args = fn.get("arguments", tc.get("arguments", "{}"))
        tc_id = str(tc.get("id") or f"call_{i}")
        if not name:
            continue
        parsed.append({"id": tc_id, "name": name, "arguments": args, "raw": tc})
    return parsed


def _merge_stream_tool_call_deltas(deltas: list) -> list[dict]:
    """Merge streamed tool_call deltas (index-based) into full tool_calls."""
    by_idx: dict[int, dict] = {}
    for delta_list in deltas:
        if not isinstance(delta_list, list):
            continue
        for d in delta_list:
            if not isinstance(d, dict):
                continue
            idx = int(d.get("index", 0))
            slot = by_idx.setdefault(
                idx,
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if d.get("id"):
                slot["id"] = d["id"]
            if d.get("type"):
                slot["type"] = d["type"]
            fn = d.get("function") if isinstance(d.get("function"), dict) else {}
            if fn.get("name"):
                slot["function"]["name"] = (slot["function"].get("name") or "") + str(fn["name"])
            if fn.get("arguments"):
                slot["function"]["arguments"] = (slot["function"].get("arguments") or "") + str(
                    fn["arguments"]
                )
    out = []
    for idx in sorted(by_idx):
        item = by_idx[idx]
        if not item.get("id"):
            item["id"] = f"call_{idx}"
        out.append(item)
    return out


async def _collect_completion(adapter, adapter_req: AdapterRequest) -> dict:
    """Run adapter to completion (force non-stream) and return aggregated result."""
    req = AdapterRequest(
        messages=adapter_req.messages,
        model=adapter_req.model,
        temperature=adapter_req.temperature,
        max_tokens=adapter_req.max_tokens,
        stream=False,
        tools=adapter_req.tools,
        tool_choice=adapter_req.tool_choice,
        stop=adapter_req.stop,
        trace_id=adapter_req.trace_id,
        request_id=adapter_req.request_id,
        privacy_policy=adapter_req.privacy_policy,
    )
    content_parts: list[str] = []
    tool_call_chunks: list = []
    finish_reason = "stop"
    usage: dict = {}
    error = None
    async for chunk in adapter.chat_completion(req):
        if chunk.finish_reason == "error":
            error = chunk.raw.get("error") if isinstance(chunk.raw, dict) else "upstream error"
            break
        if chunk.content:
            content_parts.append(chunk.content)
        if chunk.tool_calls:
            tool_call_chunks.extend(chunk.tool_calls)
        if chunk.finish_reason:
            finish_reason = chunk.finish_reason
        if chunk.usage:
            usage = chunk.usage
    # Non-stream adapters usually return full tool_calls once; stream-shaped lists need merge
    if tool_call_chunks and isinstance(tool_call_chunks[0], dict) and "index" in tool_call_chunks[0]:
        tool_calls = _merge_stream_tool_call_deltas([tool_call_chunks])
    else:
        # May already be full tool_calls; if list-of-lists, flatten merge
        if tool_call_chunks and isinstance(tool_call_chunks[0], list):
            tool_calls = _merge_stream_tool_call_deltas(tool_call_chunks)
        else:
            tool_calls = [tc for tc in tool_call_chunks if isinstance(tc, dict)]
    return {
        "content": "".join(content_parts),
        "tool_calls": tool_calls,
        "finish_reason": finish_reason,
        "usage": usage,
        "error": error,
    }


async def _run_tool_loop(
    adapter,
    adapter_req: AdapterRequest,
    *,
    max_rounds: int = _TOOL_LOOP_MAX_ROUNDS,
) -> dict:
    """
    Execute model -> tool -> model until final text.
    After tools run, synthesize with tools omitted (never tool_choice='none' —
    Groq gpt-oss rejects that when it tries built-in browser tools).
    """
    messages = list(adapter_req.messages)
    tools = adapter_req.tools
    searched = False
    imaged = False
    coded = False
    collected_results: list[str] = []
    last = {
        "content": "",
        "tool_calls": [],
        "finish_reason": "stop",
        "usage": {},
        "error": None,
    }
    rounds = 0
    tool_rounds = 0
    max_tool_rounds = max(1, max_rounds - 1)

    def _fallback_from_results() -> str:
        if not collected_results:
            return (
                "I tried to use a tool but could not finish a summary. "
                "Please try again in a moment."
            )
        # Prefer run_code / image structured dicts
        for raw in collected_results:
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict) and "exit_code" in obj and ("stdout" in obj or "stderr" in obj):
                out = str(obj.get("stdout") or "").strip()
                err = str(obj.get("stderr") or "").strip()
                lang = obj.get("language") or "python"
                parts = [f"Sandbox ran ({lang}), exit_code={obj.get('exit_code')}."]
                if out:
                    parts.append(f"Output:\n```\n{out}\n```")
                if err:
                    parts.append(f"stderr:\n```\n{err}\n```")
                return "\n\n".join(parts)
            if isinstance(obj, dict) and obj.get("ok") and (obj.get("markdown") or obj.get("url")):
                parts = []
                if obj.get("markdown"):
                    parts.append(str(obj.get("markdown")))
                url = str(obj.get("url") or "").strip()
                if url:
                    parts.append("Generated image:\n" + url)
                return "\n\n".join(parts) if parts else str(obj.get("markdown") or url)
        lines = [
            "Here is what I found on the live web (free DuckDuckGo search):",
            "",
        ]
        seen = 0
        for raw in collected_results:
            try:
                rows = json.loads(raw)
            except Exception:
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "Source").strip()
                url = str(row.get("url") or "").strip()
                sn = str(row.get("snippet") or "").strip()
                if url:
                    lines.append(f"- [{title}]({url})" + (f" — {sn}" if sn else ""))
                else:
                    lines.append(f"- {title}" + (f" — {sn}" if sn else ""))
                seen += 1
                if seen >= 6:
                    break
            if seen >= 6:
                break
        if seen == 0:
            return "Tool ran but I could not format the result. Please try again."
        lines.append("")
        lines.append("Sources cited above. Ask if you want a deeper dive on any item.")
        return "\n".join(lines)

    # Phase 1: allow tool calls
    while tool_rounds < max_tool_rounds:
        rounds += 1
        round_req = AdapterRequest(
            messages=messages,
            model=adapter_req.model,
            temperature=adapter_req.temperature,
            max_tokens=adapter_req.max_tokens,
            stream=False,
            tools=tools,
            tool_choice=adapter_req.tool_choice or ("auto" if tools else None),
            stop=adapter_req.stop,
            trace_id=adapter_req.trace_id,
            request_id=adapter_req.request_id,
            privacy_policy=adapter_req.privacy_policy,
        )
        last = await _collect_completion(adapter, round_req)
        if last.get("error"):
            break
        parsed = _parse_tool_calls(last.get("tool_calls") or [])
        if not parsed:
            break
        tool_rounds += 1
        assistant_msg: dict = {"role": "assistant", "content": last.get("content") or ""}
        assistant_msg["tool_calls"] = [
            {
                "id": p["id"],
                "type": "function",
                "function": {
                    "name": p["name"],
                    "arguments": p["arguments"]
                    if isinstance(p["arguments"], str)
                    else json.dumps(p["arguments"]),
                },
            }
            for p in parsed
        ]
        messages.append(assistant_msg)
        for p in parsed:
            if p["name"] == "web_search":
                searched = True
            if p["name"] == "generate_image":
                imaged = True
            if p["name"] == "run_code":
                coded = True
            result = execute_tool_call(p["name"], p["arguments"])
            collected_results.append(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": p["id"],
                    "content": result,
                }
            )
            print(
                f"[HAL Gateway] tool {p['name']} id={p['id']} "
                f"args={str(p['arguments'])[:120]} result_len={len(result)}"
            )

    # Phase 2: synthesize without tools (omit tools + tool_choice entirely)
    need_synth = (searched or imaged or coded) and not (last.get("content") or "").strip()
    if need_synth or ((searched or imaged or coded) and tool_rounds > 0 and (last.get("tool_calls") or [])):
        rounds += 1
        synth_messages = list(messages)
        if searched or imaged or coded:
            synth_messages.append(
                {
                    "role": "user",
                    "content": (
                        "Using the tool results already provided (web_search, generate_image, and/or run_code), "
                        "answer my original question now in clear prose. "
                        "If web_search results exist, cite sources with markdown links like "
                        "[Title](https://example.com). "
                        "If generate_image returned ok=true, include its markdown image AND the "
                        "bare URL line (Generated image: then the URL) exactly as given. "
                        "NEVER insert spaces, newlines, or soft hyphens inside any URL — "
                        "copy URLs character-for-character. "
                        "If run_code results exist, report the real stdout/stderr/exit_code "
                        "(e.g. if stdout is 4, say 4). Do not call any tools. Do not invent URLs or program output."
                    ),
                }
            )
        synth_req = AdapterRequest(
            messages=synth_messages,
            model=adapter_req.model,
            temperature=adapter_req.temperature,
            max_tokens=adapter_req.max_tokens,
            stream=False,
            tools=None,
            tool_choice=None,
            stop=adapter_req.stop,
            trace_id=adapter_req.trace_id,
            request_id=adapter_req.request_id,
            privacy_policy=adapter_req.privacy_policy,
        )
        synth = await _collect_completion(adapter, synth_req)
        if synth.get("error"):
            print(f"[HAL Gateway] synthesis failed: {synth.get('error')}; using fallback")
            last = {
                "content": _fallback_from_results(),
                "tool_calls": [],
                "finish_reason": "stop",
                "usage": last.get("usage") or {},
                "error": None,
            }
        else:
            # If model still returned empty or more tool calls, fall back
            if (synth.get("content") or "").strip():
                last = synth
            else:
                last = {
                    "content": _fallback_from_results(),
                    "tool_calls": [],
                    "finish_reason": "stop",
                    "usage": synth.get("usage") or {},
                    "error": None,
                }

    if (searched or imaged or coded) and not (last.get("content") or "").strip():
        last["content"] = _fallback_from_results()
        for raw in collected_results:
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict) and obj.get("ok") and (obj.get("markdown") or obj.get("url")):
                bits = []
                if obj.get("markdown"):
                    bits.append(str(obj.get("markdown")))
                u = str(obj.get("url") or "").strip()
                if u:
                    bits.append("Generated image:\n" + u)
                last["content"] = (
                    "\n\n".join(bits) + "\n\n" + (last.get("content") or "")
                ).strip()
                break

    last["searched"] = searched
    last["imaged"] = imaged
    last["coded"] = coded
    last["rounds"] = rounds
    last["messages"] = messages
    if (last.get("content") or "").strip():
        last["tool_calls"] = []
        last["finish_reason"] = "stop"
    return last



def build_adapter_request(req: ChatCompletionRequest, trace_id: str, request_id: str) -> AdapterRequest:
    """Convert OpenAI request to internal adapter request."""
    # Determine privacy policy from model or default
    privacy = "REMOTE_ALLOWED"
    if "local" in req.model.lower():
        privacy = "LOCAL_ONLY"

    messages = _ensure_hal_identity(_sanitize_messages(req.messages), req.model)

    # Extract required capabilities from request
    required_caps = {
        "tools": req.tools is not None and len(req.tools) > 0,
        "streaming": req.stream,
    }
    
    return AdapterRequest(
        messages=messages,
        model=req.model,
        temperature=req.temperature,
        max_tokens=_effective_max_tokens(req.model, req.max_tokens),
        stream=req.stream,
        tools=req.tools,
        tool_choice=req.tool_choice,
        stop=req.stop,
        trace_id=trace_id,
        request_id=request_id,
        privacy_policy=privacy,
    )


def map_virtual_model(model: str) -> str:
    """Map virtual model to actual virtual model key."""
    if model in VIRTUAL_MODEL_ALIASES:
        return VIRTUAL_MODEL_ALIASES[model]
    return model


# ─── Endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    voice = {"tts": False, "stt": False}
    try:
        from hal_model_gateway.piper_tts import voice_health
        voice["tts"] = bool(voice_health().get("ok"))
    except Exception:
        pass
    try:
        from hal_model_gateway.whisper_stt import stt_health
        voice["stt"] = bool(stt_health().get("ok"))
    except Exception:
        pass
    return {"status": "ok", "service": "hal-model-gateway", "voice": voice}


@app.get("/v1/images/{image_id}.png")
@app.get("/v1/images/{image_id}")
async def get_generated_image(image_id: str):
    """Public (no auth) PNG serving for markdown img tags via api.halsupreme.com."""
    path = image_file_path(image_id)
    if not path:
        raise HTTPException(404, "image not found")
    return FileResponse(
        path,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )


class SpeechRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    style: Optional[str] = None  # "singing" | "speech" — slows Piper for lyrics
    length_scale: Optional[float] = None


@app.get("/v1/audio/health")
async def audio_health(token: str = Depends(verify_token)):
    """Token-gated voice stack health (Piper + optional Whisper)."""
    from hal_model_gateway.piper_tts import voice_health
    from hal_model_gateway.whisper_stt import stt_health

    return {"status": "ok", "tts": voice_health(), "stt": stt_health()}



@app.get("/v1/audio/voices")
async def audio_voices(token: str = Depends(verify_token)):
    """List installed + planned Piper voices for the site picker."""
    from hal_model_gateway.piper_tts import list_voices, DEFAULT_VOICE
    voices = list_voices()
    return {
        "status": "ok",
        "default": DEFAULT_VOICE,
        "voices": voices,
        "ready": [v["id"] for v in voices if v.get("status") == "ready"],
    }


@app.get("/v1/audio/sfx/search")
async def audio_sfx_search(
    q: str = "",
    limit: int = 6,
    token: str = Depends(verify_token),
):
    """Search Wikimedia Commons for free/CC audio (no API key). Optional Freesound later."""
    import urllib.parse
    import urllib.request

    query = (q or "").strip()
    if not query:
        raise HTTPException(400, "q required")
    limit = max(1, min(12, int(limit or 6)))
    search_q = urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srnamespace": "6",
        "srlimit": str(limit),
        "format": "json",
        "srsearch": f"{query} filetype:audio",
    })
    search_url = f"https://commons.wikimedia.org/w/api.php?{search_q}"
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": "HAL-Supreme-Audio/1.0 (local OSS; contact: halsupreme.com)"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise HTTPException(502, f"commons search failed: {exc}") from exc

    hits = (((data or {}).get("query") or {}).get("search")) or []
    titles = [h.get("title") for h in hits if h.get("title")]
    results = []
    if titles:
        info_q = urllib.parse.urlencode({
            "action": "query",
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "format": "json",
            "titles": "|".join(titles),
        })
        info_url = f"https://commons.wikimedia.org/w/api.php?{info_q}"
        try:
            req = urllib.request.Request(info_url, headers={"User-Agent": "HAL-Supreme-Audio/1.0 (local OSS; contact: halsupreme.com)"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                info = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            raise HTTPException(502, f"commons imageinfo failed: {exc}") from exc
        pages = (((info or {}).get("query") or {}).get("pages")) or {}
        for page in pages.values():
            title = page.get("title") or ""
            ii = (page.get("imageinfo") or [{}])[0]
            url = ii.get("url")
            mime = ii.get("mime") or ""
            if not url or not str(mime).startswith("audio"):
                continue
            file_name = title.replace("File:", "", 1)
            results.append({
                "title": file_name,
                "url": url,
                "mime": mime,
                "size": ii.get("size"),
                "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                "source": "wikimedia_commons",
                "license": "see Commons file page (typically CC)",
            })
    return {
        "status": "ok",
        "q": query,
        "source": "wikimedia_commons",
        "count": len(results),
        "results": results,
        "freesound": "optional; add FREESOUND_API_KEY to secrets for richer search later",
    }


@app.post("/v1/audio/speech")
async def audio_speech(req: SpeechRequest, token: str = Depends(verify_token)):
    """FREE Piper TTS. JSON {text, voice?} → audio/wav."""
    from hal_model_gateway.piper_tts import prepare_speech_text, synthesize_wav, voice_health

    raw = (req.text or "").strip()
    if not raw:
        raise HTTPException(400, "text required")
    speech = prepare_speech_text(raw)
    if not speech:
        raise HTTPException(400, "no speakable text after projection")

    health = voice_health()
    if not health.get("ok"):
        raise HTTPException(503, f"piper not ready: {health}")

    try:
        wav = await asyncio.to_thread(
        synthesize_wav, raw, req.voice,
        style=getattr(req, "style", None),
        length_scale=getattr(req, "length_scale", None),
    )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"tts failed: {exc}") from exc

    return Response(
        content=wav,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "X-HAL-Voice": f"piper/{(req.voice or 'en_US-norman-medium')}",
            "X-HAL-Speech-Chars": str(len(speech)),
        },
    )


@app.post("/v1/audio/transcriptions")
async def audio_transcriptions(request: Request, token: str = Depends(verify_token)):
    """FREE Whisper STT. multipart form field 'file' (or 'audio') → {text}."""
    from hal_model_gateway.whisper_stt import stt_health, transcribe_bytes

    health = stt_health()
    if not health.get("ok"):
        raise HTTPException(503, f"whisper not ready: {health}")

    form = await request.form()
    upload = form.get("file") or form.get("audio")
    if upload is None:
        raise HTTPException(400, "multipart field 'file' (or 'audio') required")

    filename = getattr(upload, "filename", None) or "audio.webm"
    if hasattr(upload, "read"):
        data = await upload.read()
    else:
        data = bytes(upload)

    model_name = form.get("model")
    if isinstance(model_name, bytes):
        model_name = model_name.decode("utf-8", errors="replace")
    model_name = str(model_name).strip() if model_name else None

    try:
        result = await asyncio.to_thread(transcribe_bytes, data, str(filename), model_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"transcription failed: {exc}") from exc

    return {
        "text": result["text"],
        "language": result.get("language", "en"),
        "model": result.get("model"),
        "object": "transcription",
    }



def load_peers_config() -> dict:
    """Load optional config/peers.json; never raises to callers."""
    try:
        raw = _PEERS_CONFIG_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"version": "2026-09-23", "peers": {}}


@app.get("/v1/peers")
async def list_peers(token: str = Depends(verify_token)):
    """HAL self identity + enabled peers from config/peers.json (no outbound calls)."""
    cfg = load_peers_config()
    peers_map = cfg.get("peers") or {}
    if not isinstance(peers_map, dict):
        peers_map = {}

    self_entry = {
        "id": "hal-supreme",
        "kind": "self",
        "name": "HAL SUPREME",
        "base_url": "https://api.halsupreme.com",
        "openai_base_url": "https://api.halsupreme.com/v1",
        "capabilities": ["chat", "models", "mcp", "audio", "images"],
        "models": list(VIRTUAL_MODELS.keys()),
        "models_path": "/v1/models",
        "protocols": ["openai-compat", "mcp"],
        "tools": ["web_search", "generate_image", "run_code"],
        "mcp": {
            "hint": "python -m hal_mcp.gateway_server",
            "env": {"HAL_GATEWAY_URL": "http://127.0.0.1:8766"},
        },
    }

    data = [self_entry]
    for peer_id, peer in peers_map.items():
        if not isinstance(peer, dict):
            continue
        if not bool(peer.get("enabled", False)):
            continue
        data.append({
            "id": str(peer_id),
            "kind": peer.get("kind") or "openai_compat",
            "name": peer.get("name") or str(peer_id),
            "base_url": peer.get("base_url"),
            "capabilities": peer.get("capabilities") or ["chat"],
            "models": peer.get("allowed_models") or [],
            "billing_class": peer.get("billing_class"),
            "privacy_class": peer.get("privacy_class"),
            "protocols": ["openai-compat"] if (peer.get("kind") or "openai_compat") == "openai_compat" else [str(peer.get("kind"))],
            "enabled": True,
        })

    return {
        "object": "list",
        "version": cfg.get("version") or "2026-09-23",
        "data": data,
    }


@app.get("/v1/models", response_model=ModelsResponse)
async def list_models(token: str = Depends(verify_token)):
    """List virtual models (what OpenCode sees)."""
    models = []
    for model_id, config in VIRTUAL_MODELS.items():
        models.append(ModelInfo(
            id=model_id,
            created=int(time.time()),
            owned_by="hal",
        ))
    return ModelsResponse(data=models)


@app.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    request: Request,
    token: str = Depends(verify_token),
):
    """OpenAI-compatible chat completions endpoint (with free web_search tool loop)."""
    trace_id = uuid.uuid4().hex[:16]
    request_id = uuid.uuid4().hex[:12]
    start_time = time.time()

    virtual_model = map_virtual_model(req.model)
    if virtual_model not in VIRTUAL_MODELS:
        raise HTTPException(400, f"Unknown model: {req.model}. Available: {list(VIRTUAL_MODELS.keys())}")

    from .contracts import RoutingRequest, ModelCapabilities

    offer_search_hint = virtual_model in _MODELS_ALWAYS_OFFER_SEARCH or bool(req.tools)
    routing_req = RoutingRequest(
        virtual_model=virtual_model,
        required_capabilities=ModelCapabilities(
            tools=offer_search_hint or (req.tools is not None and len(req.tools) > 0),
            streaming=req.stream,
        ),
        privacy_policy="LOCAL_ONLY" if "local" in req.model.lower() else "REMOTE_ALLOWED",
        trace_id=trace_id,
        request_id=request_id,
    )

    route_start = time.time()
    route_decision = _router.route(routing_req)
    route_ms = (time.time() - route_start) * 1000

    if not route_decision.provider:
        raise HTTPException(503, f"No available provider: {route_decision.reason}")

    adapter_req = build_adapter_request(req, trace_id, request_id)
    adapter_req.model = route_decision.model

    # Local ollama fast: heuristic search/image/code then-augment (no tool protocol)
    augmented = False
    image_augmented = False
    code_augmented = False
    if not req.tools:
        adapter_req.messages, augmented = _maybe_augment_with_search(
            adapter_req.messages, virtual_model, route_decision.provider
        )
        adapter_req.messages, image_augmented = _maybe_augment_with_image(
            adapter_req.messages, virtual_model, route_decision.provider
        )
        adapter_req.messages, code_augmented = _maybe_augment_with_code(
            adapter_req.messages, virtual_model, route_decision.provider
        )

    user_text = _last_user_text(adapter_req.messages)
    offer_search = _should_offer_web_search(virtual_model, route_decision.provider, user_text)
    offer_image = _should_offer_image(virtual_model, route_decision.provider, user_text)
    offer_code = _should_offer_run_code(virtual_model, route_decision.provider, user_text)
    if req.tools is not None:
        offer_search = True
        offer_image = True
        offer_code = True
    merged_tools = _merge_tools(
        req.tools,
        offer_search=offer_search and not augmented,
        offer_image=offer_image and not image_augmented,
        offer_code=offer_code and not code_augmented,
    )
    adapter_req.tools = merged_tools
    if merged_tools and not adapter_req.tool_choice:
        adapter_req.tool_choice = req.tool_choice or "auto"

    adapter = await _adapter_manager.get_adapter(route_decision.provider, route_decision.model)
    if not adapter:
        raise HTTPException(503, f"Failed to create adapter for {route_decision.provider}/{route_decision.model}")

    use_tool_loop = bool(merged_tools)

    if req.stream:
        return StreamingResponse(
            stream_chat(
                adapter,
                adapter_req,
                route_decision,
                trace_id,
                request_id,
                start_time,
                route_ms,
                virtual_model=virtual_model,
                tool_required=bool(merged_tools),
                use_tool_loop=use_tool_loop,
                searched_already=augmented,
                imaged_already=image_augmented,
                coded_already=code_augmented,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Request-ID": request_id,
                "X-Trace-ID": trace_id,
            },
        )

    # Non-streaming
    searched = augmented
    imaged = image_augmented
    coded = code_augmented
    content = ""
    tool_calls: list = []
    finish_reason = "stop"
    usage: dict = {}

    if use_tool_loop:
        result = await _run_tool_loop(adapter, adapter_req)
        if result.get("error"):
            raise HTTPException(502, f"Upstream provider failed: {result['error']}")
        content = result.get("content") or ""
        tool_calls = result.get("tool_calls") or []
        finish_reason = result.get("finish_reason") or "stop"
        usage = result.get("usage") or {}
        searched = searched or bool(result.get("searched"))
        imaged = imaged or bool(result.get("imaged"))
        coded = coded or bool(result.get("coded"))
        # If the model ended on tool_calls without a final text turn, strip tool_calls from client view
        if content and tool_calls and finish_reason == "tool_calls":
            tool_calls = []
            finish_reason = "stop"
        elif not content and tool_calls:
            # Exhausted rounds on tools — return a short note
            content = "I looked that up but could not finish summarizing. Please try again."
            tool_calls = []
            finish_reason = "stop"
    else:
        async for chunk in adapter.chat_completion(adapter_req):
            if chunk.finish_reason == "error":
                error = chunk.raw.get("error") if isinstance(chunk.raw, dict) else None
                raise HTTPException(502, f"Upstream provider failed: {error or 'unknown provider error'}")
            content += chunk.content or ""
            if chunk.tool_calls:
                tool_calls.extend(chunk.tool_calls)
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if chunk.usage:
                usage = chunk.usage

    total_ms = (time.time() - start_time) * 1000
    telemetry = GatewayTelemetry(
        request_id=request_id,
        trace_id=trace_id,
        virtual_model=virtual_model,
        selected_provider=route_decision.provider,
        selected_model=route_decision.model,
        route_ms=route_ms,
        total_ms=total_ms,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        cost_usd=0.0,
        tool_required=bool(merged_tools),
    )
    emit_gateway_telemetry(telemetry)
    if searched:
        print(f"[HAL Gateway] web_search used request_id={request_id} model={virtual_model}")
    if imaged:
        print(f"[HAL Gateway] image_gen used request_id={request_id} model={virtual_model}")
    if coded:
        print(f"[HAL Gateway] run_code used request_id={request_id} model={virtual_model}")

    message: dict = {
        "role": "assistant",
        "content": content,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls

    resp = {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason,
        }],
        "usage": usage,
    }
    meta = {}
    if searched:
        meta["web_search"] = True
    if imaged:
        meta["image_gen"] = True
    if coded:
        meta["run_code"] = True
    if meta:
        resp["hal_meta"] = meta
    return resp


async def stream_chat(
    adapter,
    adapter_req: AdapterRequest,
    route_decision,
    trace_id: str,
    request_id: str,
    start_time: float,
    route_ms: float,
    *,
    virtual_model: str,
    tool_required: bool = False,
    use_tool_loop: bool = False,
    searched_already: bool = False,
    imaged_already: bool = False,
    coded_already: bool = False,
) -> AsyncGenerator[str, None]:
    """Stream chat completion as SSE. When tools are offered, run the tool loop then stream final text."""
    first_token = True
    ttft_ms = None
    content_parts: list[str] = []
    tool_calls: list = []
    finish_reason = "stop"
    usage: dict = {}
    max_stream_gap = 0.0
    last_chunk_time = time.time()
    retry_count = 0
    cancelled = False
    failure_reason = None
    searched = searched_already
    imaged = imaged_already
    coded = coded_already

    def _sse(delta: dict, fr=None) -> str:
        payload = {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion.chunk",
            "created": int(start_time),
            "model": adapter_req.model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": fr,
            }],
        }
        return f"data: {json.dumps(payload)}\n\n"

    try:
        if use_tool_loop:
            # Emit immediate status so clients are not stuck on empty Generating
            # while the (non-streaming) tool loop runs to completion.
            yield ": hal-tool-loop\n\n"
            yield (
                "data: "
                + json.dumps({
                    "id": f"chatcmpl-{request_id}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": virtual_model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                    "hal_meta": {"status": "tools", "tool_loop": True},
                })
                + "\n\n"
            )
            result = await _run_tool_loop(adapter, adapter_req)
            if result.get("error"):
                raise RuntimeError(f"Upstream provider failed: {result['error']}")
            searched = searched or bool(result.get("searched"))
            imaged = imaged or bool(result.get("imaged"))
            coded = coded or bool(result.get("coded"))
            content = result.get("content") or ""
            finish_reason = "stop"
            usage = result.get("usage") or {}
            # Stream path must never finish with a blank bubble (matches non-stream fallback).
            if not str(content).strip():
                if result.get("tool_calls"):
                    content = "I looked that up but could not finish summarizing. Please try again."
                elif searched or imaged or coded:
                    content = "I ran tools but could not finish summarizing. Please try again."
                else:
                    content = "No reply came back from the model. Please try again."
            if searched or imaged or coded:
                hm = {}
                if searched:
                    hm["web_search"] = True
                if imaged:
                    hm["image_gen"] = True
                if coded:
                    hm["run_code"] = True
                meta = {
                    "id": f"chatcmpl-{request_id}",
                    "object": "chat.completion.chunk",
                    "created": int(start_time),
                    "model": adapter_req.model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                    "hal_meta": hm,
                }
                yield f"data: {json.dumps(meta)}\n\n"
            if content:
                if first_token:
                    ttft_ms = (time.time() - start_time) * 1000
                    first_token = False
                # Emit in modest chunks so the UI still feels streaming
                step = 48
                for i in range(0, len(content), step):
                    piece = content[i : i + step]
                    content_parts.append(piece)
                    yield _sse({"content": piece})
            yield _sse({}, finish_reason)
            yield "data: [DONE]\n\n"
        else:
            async for chunk in adapter.chat_completion(adapter_req):
                if chunk.finish_reason == "error":
                    error = chunk.raw.get("error") if isinstance(chunk.raw, dict) else None
                    raise RuntimeError(f"Upstream provider failed: {error or 'unknown provider error'}")
                if first_token:
                    ttft_ms = (time.time() - start_time) * 1000
                    first_token = False

                now = time.time()
                gap = (now - last_chunk_time) * 1000
                max_stream_gap = max(max_stream_gap, gap)
                last_chunk_time = now

                content_parts.append(chunk.content or "")
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                if chunk.usage:
                    usage = chunk.usage

                delta = {}
                if chunk.content:
                    delta["content"] = chunk.content
                if chunk.tool_calls:
                    delta["tool_calls"] = chunk.tool_calls

                yield _sse(delta, chunk.finish_reason if chunk.finish_reason else None)

            if searched or imaged or coded:
                hm = {}
                if searched:
                    hm["web_search"] = True
                if imaged:
                    hm["image_gen"] = True
                if coded:
                    hm["run_code"] = True
                meta = {
                    "id": f"chatcmpl-{request_id}",
                    "object": "chat.completion.chunk",
                    "created": int(start_time),
                    "model": adapter_req.model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                    "hal_meta": hm,
                }
                yield f"data: {json.dumps(meta)}\n\n"

            yield _sse({}, finish_reason)
            yield "data: [DONE]\n\n"

    except asyncio.CancelledError:
        cancelled = True
        emit_gateway_event("REQUEST_CANCELLED", trace_id, virtual_model, {
            "request_id": request_id,
            "provider": route_decision.provider,
        })
        raise
    except Exception as e:
        failure_reason = f"{type(e).__name__}: {e}"
        error_data = {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion.chunk",
            "created": int(start_time),
            "model": adapter_req.model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "error",
            }],
            "error": {"message": str(e), "type": "gateway_error"},
        }
        yield f"data: {json.dumps(error_data)}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        total_ms = (time.time() - start_time) * 1000
        telemetry = GatewayTelemetry(
            request_id=request_id,
            trace_id=trace_id,
            virtual_model=virtual_model,
            selected_provider=route_decision.provider,
            selected_model=route_decision.model,
            route_ms=route_ms,
            ttft_ms=ttft_ms,
            total_ms=total_ms,
            max_stream_gap_ms=max_stream_gap,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            retry_count=retry_count,
            failure_reason=failure_reason,
            cancelled=cancelled,
            tool_required=tool_required,
            tool_valid=bool(tool_calls) if tool_required else True,
        )
        emit_gateway_telemetry(telemetry)
        if searched:
            print(f"[HAL Gateway] web_search used (stream) request_id={request_id} model={virtual_model}")
        if imaged:
            print(f"[HAL Gateway] image_gen used (stream) request_id={request_id} model={virtual_model}")
        if coded:
            print(f"[HAL Gateway] run_code used (stream) request_id={request_id} model={virtual_model}")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
