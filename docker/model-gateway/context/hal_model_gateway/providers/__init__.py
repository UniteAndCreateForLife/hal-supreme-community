"""
HAL Model Gateway — Provider Adapters
=====================================

Thin wrappers around provider APIs. Each adapter handles:
- Request translation
- SSE streaming
- Cancellation
- Error normalization
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

import aiohttp

from hal_model_gateway.contracts import ProviderCapabilities, ModelCapabilities, ProviderHealth


# ─── Base Adapter ────────────────────────────────────────────────────────

@dataclass
class AdapterRequest:
    """Normalized request for any provider."""
    messages: list[dict]
    model: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    tools: Optional[list] = None
    tool_choice: Optional[str] = None
    stop: Optional[list] = None
    trace_id: str = ""
    request_id: str = ""
    privacy_policy: str = "REMOTE_ALLOWED"


@dataclass
class AdapterResponse:
    """Normalized response from any provider."""
    content: str = ""
    tool_calls: list = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


class ProviderAdapter(ABC):
    """Base class for provider adapters."""
    
    def __init__(self, capabilities: ProviderCapabilities):
        self.capabilities = capabilities
        self.session: Optional[aiohttp.ClientSession] = None
        self._cancelled = False
    
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=300, connect=10)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    @abstractmethod
    async def chat_completion(self, req: AdapterRequest) -> AsyncGenerator[AdapterResponse, None]:
        """Stream chat completion chunks."""
        yield
    
    @abstractmethod
    async def list_models(self) -> list[str]:
        """List available models from this provider."""
        pass
    
    def cancel(self):
        self._cancelled = True
    
    def _get_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.capabilities.api_key}" if self.capabilities.api_key else "",
        }
    
    def _build_payload(self, req: AdapterRequest) -> dict:
        payload = {
            "model": req.model,
            "messages": req.messages,
            "temperature": req.temperature,
            "stream": req.stream,
        }
        if req.max_tokens:
            payload["max_tokens"] = req.max_tokens
        if req.tools:
            payload["tools"] = req.tools
        if req.tool_choice:
            payload["tool_choice"] = req.tool_choice
        if req.stop:
            payload["stop"] = req.stop
        return payload


# ─── Ollama Adapter ──────────────────────────────────────────────────────

class OllamaAdapter(ProviderAdapter):
    """Ollama local provider adapter."""

    def _native_base_url(self) -> str:
        base_url = self.capabilities.base_url.rstrip("/")
        return base_url[:-3] if base_url.endswith("/v1") else base_url
    
    async def chat_completion(self, req: AdapterRequest) -> AsyncGenerator[AdapterResponse, None]:
        if not self.session:
            raise RuntimeError("Adapter not initialized")
        
        payload = self._build_payload(req)
        payload["model"] = req.model
        
        url = f"{self._native_base_url()}/api/chat"
        
        try:
            async with self.session.post(url, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    yield AdapterResponse(
                        content="",
                        finish_reason="error",
                        raw={"error": error_text, "status": resp.status},
                    )
                    return
                
                if req.stream:
                    async for line in resp.content:
                        if self._cancelled:
                            break
                        line = line.decode("utf-8").strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            message = data.get("message", {})
                            content = message.get("content", "")
                            if content:
                                yield AdapterResponse(
                                    content=content,
                                    finish_reason="length" if data.get("done") else "",
                                    raw=data,
                                )
                            if data.get("done"):
                                yield AdapterResponse(
                                    content="",
                                    finish_reason="stop",
                                    usage=data.get("eval_count", {}),
                                    raw=data,
                                )
                                break
                        except json.JSONDecodeError:
                            continue
                else:
                    data = await resp.json()
                    message = data.get("message", {})
                    yield AdapterResponse(
                        content=message.get("content", ""),
                        finish_reason="stop",
                        usage={"completion_tokens": data.get("eval_count", 0)},
                        raw=data,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield AdapterResponse(
                content="",
                finish_reason="error",
                raw={"error": str(e)},
            )
    
    async def list_models(self) -> list[str]:
        if not self.session:
            raise RuntimeError("Adapter not initialized")
        
        async with self.session.get(f"{self._native_base_url()}/api/tags") as resp:
            if resp.status == 200:
                data = await resp.json()
                return [m["name"] for m in data.get("models", [])]
        return []


# ─── OpenAI-Compatible Adapter ──────────────────────────────────────────

class OpenAICompatibleAdapter(ProviderAdapter):
    """Generic OpenAI-compatible API adapter (Groq, OpenRouter, etc.)."""
    
    def __init__(self, capabilities: ProviderCapabilities):
        super().__init__(capabilities)
        api_key_env = getattr(capabilities, "api_key_env", "") or ""
        # Normalize $VAR / ${VAR} / plain VAR from OpenCode config
        m = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", str(api_key_env).strip())
        if m:
            api_key_env = m.group(1)
        elif str(api_key_env).startswith("$"):
            api_key_env = str(api_key_env)[1:]
        if api_key_env in ("", "not-needed"):
            self._api_key = ""
        else:
            self._api_key = os.environ.get(api_key_env, "")
    
    def _get_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers
    
    async def chat_completion(self, req: AdapterRequest) -> AsyncGenerator[AdapterResponse, None]:
        if not self.session:
            raise RuntimeError("Adapter not initialized")
        
        payload = self._build_payload(req)
        
        url = f"{self.capabilities.base_url}/chat/completions"
        
        try:
            async with self.session.post(url, json=payload, headers=self._get_headers()) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    yield AdapterResponse(
                        content="",
                        finish_reason="error",
                        raw={"error": error_text, "status": resp.status},
                    )
                    return
                
                if req.stream:
                    async for line in resp.content:
                        if self._cancelled:
                            break
                        line = line.decode("utf-8").strip()
                        if not line or not line.startswith("data: "):
                            continue
                        if line == "data: [DONE]":
                            yield AdapterResponse(content="", finish_reason="stop")
                            break
                        try:
                            data = json.loads(line[6:])
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content") or ""
                                tool_calls = delta.get("tool_calls", [])
                                if content:
                                    yield AdapterResponse(content=content, finish_reason="")
                                if tool_calls:
                                    yield AdapterResponse(content="", tool_calls=tool_calls, finish_reason="")
                                if choices[0].get("finish_reason"):
                                    finish_reason = choices[0]["finish_reason"]
                                    usage = data.get("usage", {})
                                    yield AdapterResponse(
                                        content="",
                                        finish_reason=finish_reason,
                                        usage=usage,
                                    )
                        except json.JSONDecodeError:
                            continue
                else:
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        yield AdapterResponse(
                            content=(msg.get("content") or ""),
                            tool_calls=msg.get("tool_calls", []),
                            finish_reason=choices[0].get("finish_reason", "stop"),
                            usage=data.get("usage", {}),
                            raw=data,
                        )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield AdapterResponse(
                content="",
                finish_reason="error",
                raw={"error": str(e)},
            )
    
    async def list_models(self) -> list[str]:
        # Most OpenAI-compatible APIs don't have a standard /models endpoint
        # Return the configured model
        return [self.capabilities.model]


# ─── Adapter Factory ─────────────────────────────────────────────────────

def create_adapter(provider: str, capabilities: ProviderCapabilities) -> ProviderAdapter:
    """Create appropriate adapter for provider."""
    provider_lower = provider.lower()
    
    if "ollama" in provider_lower or "127.0.0.1:11434" in capabilities.base_url:
        return OllamaAdapter(capabilities)
    elif "openai" in provider_lower or "groq" in provider_lower or "openrouter" in provider_lower:
        return OpenAICompatibleAdapter(capabilities)
    else:
        # Default to OpenAI-compatible
        return OpenAICompatibleAdapter(capabilities)


# ─── Adapter Manager ─────────────────────────────────────────────────────

class AdapterManager:
    """Manages adapter lifecycle and provides unified interface."""
    
    def __init__(self, registry: ProviderRegistry):
        self.registry = registry
        self._adapters: dict[str, ProviderAdapter] = {}
        self._lock = asyncio.Lock()
    
    async def get_adapter(self, provider: str, model: str) -> Optional[ProviderAdapter]:
        """Get or create adapter for provider/model."""
        key = f"{provider}/{model}"
        
        async with self._lock:
            if key in self._adapters:
                return self._adapters[key]
            
            caps = self.registry.get(provider, model)
            if not caps:
                return None
            
            adapter = create_adapter(provider, caps)
            await adapter.__aenter__()
            self._adapters[key] = adapter
            return adapter
    
    async def close_adapter(self, provider: str, model: str):
        """Close and remove adapter."""
        key = f"{provider}/{model}"
        async with self._lock:
            if key in self._adapters:
                await self._adapters[key].__aexit__(None, None, None)
                del self._adapters[key]
    
    async def close_all(self):
        """Close all adapters."""
        async with self._lock:
            for adapter in self._adapters.values():
                await adapter.__aexit__(None, None, None)
            self._adapters.clear()
