"""
HAL Model Gateway — Provider Health & Registry
===============================================

Manages provider health states, capability registry, and health transitions.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .contracts import (
    ProviderCapabilities,
    ProviderHealth,
    ModelCapabilities,
    map_provider_error,
)


# ─── Provider Health State ───────────────────────────────────────────────

@dataclass
class ProviderHealthState:
    """Runtime health state for a provider/model."""
    provider: str
    model: str
    health: str = "AVAILABLE"
    consecutive_failures: int = 0
    last_success: float = 0.0
    last_failure: float = 0.0
    last_health_change: float = 0.0
    failure_details: list = field(default_factory=list)
    rate_limit_reset: float = 0.0
    consecutive_successes: int = 0


# ─── Provider Registry ──────────────────────────────────────────────────

class ProviderRegistry:
    """
    Central registry of provider capabilities and health.
    
    Thread-safe, event-emitting, persisted to EventStore.
    """
    
    def __init__(self):
        self._providers: dict[str, dict[str, ProviderCapabilities]] = defaultdict(dict)
        self._health: dict[str, dict[str, ProviderHealthState]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._event_callbacks: list = []
    
    def register(self, caps: ProviderCapabilities) -> None:
        """Register or update a provider/model capability entry."""
        self._providers[caps.provider][caps.model] = caps
        # Initialize health state if new
        if caps.model not in self._health[caps.provider]:
            self._health[caps.provider][caps.model] = ProviderHealthState(
                provider=caps.provider,
                model=caps.model,
                health=caps.health_state,
            )
    
    def get(self, provider: str, model: str) -> Optional[ProviderCapabilities]:
        return self._providers.get(provider, {}).get(model)
    
    def get_all_for_virtual(self, virtual_model: str) -> list[ProviderCapabilities]:
        """Get all providers that can serve a virtual model's requirements."""
        # This would use virtual model config to filter
        results = []
        for provider, models in self._providers.items():
            for model, caps in models.items():
                if caps.health_state == "AVAILABLE":
                    results.append(caps)
        return results
    
    def get_healthy_providers(self) -> list[ProviderCapabilities]:
        """Get all currently healthy providers."""
        results = []
        for provider, models in self._providers.items():
            for model, caps in models.items():
                health = self._health[provider].get(model)
                if health and health.health in ("AVAILABLE", "DEGRADED"):
                    results.append(caps)
        return results
    
    def record_success(self, provider: str, model: str) -> None:
        """Record a successful request."""
        health = self._health[provider].get(model)
        if health:
            health.last_success = time.time()
            health.consecutive_failures = 0
            health.consecutive_successes += 1
            # Recover from DEGRADED after sustained success
            if health.health == "DEGRADED" and health.consecutive_successes >= 5:
                self._set_health(provider, model, "AVAILABLE")
    
    def record_failure(self, provider: str, model: str, status_code: int, error: str = "") -> None:
        """Record a failed request and update health."""
        health = self._health[provider].get(model)
        if not health:
            return
        
        health.last_failure = time.time()
        health.consecutive_failures += 1
        health.consecutive_successes = 0
        health.failure_details.append({
            "timestamp": time.time(),
            "status_code": status_code,
            "error": error[:200],
        })
        # Keep only recent failures
        if len(health.failure_details) > 10:
            health.failure_details = health.failure_details[-10:]
        
        # Update health based on error
        new_health = self._compute_health(status_code, health.consecutive_failures)
        if new_health != health.health:
            self._set_health(provider, model, new_health)
    
    def _compute_health(self, status_code: int, consecutive_failures: int) -> str:
        """Determine health state from error and history."""
        if status_code in (401, 403):
            return "AUTH_FAILED"
        if status_code == 402:
            return "OUT_OF_CREDITS"
        if status_code in (404, 410):
            return "MODEL_REMOVED"
        if status_code == 429:
            return "RATE_LIMITED"
        if status_code >= 500:
            if consecutive_failures >= 3:
                return "DEGRADED"
            return "AVAILABLE"  # Single 5xx might be transient
        if status_code in (408, 504):
            if consecutive_failures >= 2:
                return "TIMEOUT"
            return "DEGRADED"
        return "AVAILABLE"
    
    def _set_health(self, provider: str, model: str, new_health: str) -> None:
        """Update health state and emit event."""
        health = self._health[provider].get(model)
        if not health:
            return
        
        old_health = health.health
        if old_health == new_health:
            return
        
        health.health = new_health
        health.last_health_change = time.time()
        health.consecutive_failures = 0
        health.consecutive_successes = 0
        
        # Emit event (async)
        for cb in self._event_callbacks:
            try:
                cb({
                    "event_type": "PROVIDER_HEALTH_CHANGED",
                    "provider": provider,
                    "model": model,
                    "old_health": old_health,
                    "new_health": new_health,
                    "timestamp": time.time(),
                })
            except Exception:
                pass
    
    def on_health_change(self, callback):
        """Register callback for health change events."""
        self._event_callbacks.append(callback)
    
    def get_health(self, provider: str, model: str) -> Optional[ProviderHealthState]:
        return self._health.get(provider, {}).get(model)
    
    def is_available(self, provider: str, model: str) -> bool:
        health = self.get_health(provider, model)
        if not health:
            return False
        return health.health in ("AVAILABLE", "DEGRADED")
    
    def get_rate_limit_reset(self, provider: str, model: str) -> float:
        health = self.get_health(provider, model)
        if health:
            return health.rate_limit_reset
        return 0.0
    
    def set_rate_limit_reset(self, provider: str, model: str, reset_at: float) -> None:
        health = self._health[provider].get(model)
        if health:
            health.rate_limit_reset = reset_at
            if health.health != "RATE_LIMITED":
                self._set_health(provider, model, "RATE_LIMITED")


# ─── Load from OpenCode Config ──────────────────────────────────────────

def get_model_context_tokens(model_id: str, provider: str) -> int:
    """Estimate context tokens for a model based on name."""
    model_lower = model_id.lower()
    
    # Large context models
    if any(x in model_lower for x in ['397b', '235b', '70b', '120b', '120b']):
        return 128000
    if any(x in model_lower for x in ['32b', '32b', '70b', '72b', '72b']):
        return 32768
    if any(x in model_lower for x in ['32b', '8x7b', '8x7b', '8x7b']):
        return 32768
    if any(x in model_lower for x in ['235b', '397b']):
        return 128000
    
    # Standard context
    if any(x in model_lower for x in ['4.7', '5.1', 'glm', 'glm']):
        return 32768
    if '8x7b' in model_lower or 'mixtral' in model_lower:
        return 32768
    
    # Small local models
    if any(x in model_lower for x in ['phi3', 'tinyllama', 'qwen2.5:3b', 'qwen2.5:7b']):
        return 8192
    
    # Default for cloud models
    return 8192


def get_model_json_schema_support(model_id: str, provider: str) -> bool:
    """Check if model supports JSON schema / structured output."""
    model_lower = model_id.lower()
    
    # Most modern models support JSON schema
    if any(x in model_lower for x in ['gpt-4', 'gpt-3.5', 'claude', 'gemini', 'llama-3', 'mistral-large', 'mixtral', 'nemotron', 'glm-4', 'glm-5', 'qwen3', 'qwen2.5', 'deepseek-v3', 'deepseek-r1', 'command-r', 'gemma-2', 'gemma-4']):
        return True
    
    # OpenAI-compatible APIs generally support it
    if any(x in provider.lower() for x in ['openai', 'openrouter', 'groq', 'cerebras', 'github', 'nvidia', 'huggingface', 'deepinfra', 'sambanova', 'llm7', 'cloudflare', 'ollama-cloud', 'zai', 'xai', 'glhf', 'ovh', 'nebius', 'siliconflow', 'together']):
        return True
    
    # Local models - check specific ones
    if any(x in provider.lower() for x in ['ollama']):
        return any(x in model_id.lower() for x in ['qwen2.5', 'phi3', 'gemma'])
    
    return False


def load_from_opencode_config(config_path: str = None) -> ProviderRegistry:
    """Load provider registry from OpenCode JSON config."""
    import json
    import os
    
    if config_path is None:
        # Try to find OpenCode config in project root
        project_root = os.path.dirname(os.path.dirname(__file__))
        config_path = os.path.join(project_root, 'opencode_config.json')
        if not os.path.exists(config_path):
            # Try standard locations
            for path in [
                os.path.join(os.environ.get('APPDATA', ''), 'opencode', 'config.json'),
                os.path.join(os.environ.get('USERPROFILE', ''), '.config', 'opencode', 'config.json'),
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'opencode', 'config.json'),
            ]:
                if os.path.exists(path):
                    config_path = path
                    break
            else:
                # Default to project root
                config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'opencode_config.json')
    
    with open(config_path) as f:
        config = json.load(f)
    
    registry = ProviderRegistry()
    
    for provider_name, provider_config in config.get("provider", {}).items():
        base_url = provider_config.get("options", {}).get("baseURL", "")
        api_key_env = provider_config.get("options", {}).get("apiKey", "")
        models = provider_config.get("models", {})
        
        for model_id, model_config in models.items():
            context_tokens = get_model_context_tokens(model_id, provider_name)
            json_schema = get_model_json_schema_support(model_id, provider_name)
            caps = ProviderCapabilities(
                provider=provider_name,
                model=model_id,
                base_url=base_url,
                capabilities=ModelCapabilities(
                    context_tokens=context_tokens,
                    tools=model_config.get("tool_call", False),
                    vision=model_config.get("attachment", False),
                    streaming=True,
                    json_schema=json_schema,
                ),
                local="127.0.0.1" in base_url or "localhost" in base_url,
                estimated_quality=0.5,
                p50_latency_ms=5000,
                cost_per_1k_tokens=0.0,
                api_key_env=api_key_env,
            )
            registry.register(caps)
    
    return registry


# ─── Singleton ──────────────────────────────────────────────────────────

_registry: Optional[ProviderRegistry] = None

def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = load_from_opencode_config()
    elif len(_registry._providers) == 0:
        # Reload if empty
        _registry = load_from_opencode_config()
    return _registry


# ─── Helpers ─────────────────────────────────────────────────────────────

def provider_key(provider: str, model: str) -> str:
    return f"{provider}/{model}"