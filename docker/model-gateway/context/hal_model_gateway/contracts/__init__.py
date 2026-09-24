"""
HAL Model Gateway — Contracts
=============================

Virtual model definitions, capability contracts, and provider health states.
These are the SERVICE CLASSES that OpenCode sees — HAL handles the routing.
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ─── Virtual Models ──────────────────────────────────────────────────────

VIRTUAL_MODELS = {
    "hal/fast": {
        "name": "HAL Fast",
        "description": "Latency-first; cloud preferred (Ollama last-resort) for simple search/edit/debug",
        "capabilities": {
            "tool_calling": True,
            "streaming": True,
            "context_tokens": 8192,
            "vision": False,
            "json_schema": False,
        },
        "routing": {
            "preferred_providers": ["free_cloud", "local"],
            "latency_target_ms": 2000,
            "quality_floor": 0.6,
            "cloud_first": True,
        },
    },
    "hal/coder": {
        "name": "HAL Coder",
        "description": "Coding quality first, tools required, safe context floor",
        "capabilities": {
            "tool_calling": True,
            "streaming": True,
            "context_tokens": 32768,
            "vision": False,
            "json_schema": True,
        },
        "routing": {
            "preferred_providers": ["free_cloud", "local"],
            "latency_target_ms": 5000,
            "quality_floor": 0.8,
            "require_tools": True,
            "cloud_first": True,
        },
    },
    "hal/deep": {
        "name": "HAL Deep",
        "description": "Hard reasoning, large context, strongest eligible route",
        "capabilities": {
            "tool_calling": True,
            "streaming": True,
            "context_tokens": 128000,
            "vision": False,
            "json_schema": True,
        },
        "routing": {
            "preferred_providers": ["free_cloud", "premium", "local"],
            "latency_target_ms": 15000,
            "quality_floor": 0.9,
            "cloud_first": True,
        },
    },
    "hal/council": {
        "name": "HAL Council",
        "description": "Multi-perspective deliberation (lighter v1: single deep synthesis with structured Council sections)",
        "capabilities": {
            "tool_calling": True,
            "streaming": True,
            "context_tokens": 128000,
            "vision": False,
            "json_schema": True,
        },
        "routing": {
            "preferred_providers": ["free_cloud", "local"],
            "latency_target_ms": 20000,
            "quality_floor": 0.85,
            "cloud_first": True,
        },
    },
}


# ─── Capability Contracts ────────────────────────────────────────────────

@dataclass
class ModelCapabilities:
    """What a model/provider can actually do."""
    context_tokens: int = 4096
    tools: bool = False
    vision: bool = False
    json_schema: bool = False
    streaming: bool = True
    max_output_tokens: int = 4096
    supported_tool_types: list = field(default_factory=list)
    supported_formats: list = field(default_factory=list)


@dataclass
class ProviderCapabilities:
    """Provider-level metadata for routing decisions."""
    provider: str
    model: str
    base_url: str
    capabilities: ModelCapabilities
    local: bool = False
    privacy_classes: list = field(default_factory=list)
    estimated_quality: float = 0.5
    p50_latency_ms: float = 5000
    p95_latency_ms: float = 30000
    cost_per_1k_tokens: float = 0.0
    rate_limit_rpm: int = 60
    rate_limit_state: str = "AVAILABLE"
    health_state: str = "AVAILABLE"
    last_success: float = 0.0
    last_failure: float = 0.0
    consecutive_failures: int = 0
    api_key_env: str = ""


# ─── Health States ──────────────────────────────────────────────────────

class ProviderHealth(enum.Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    OUT_OF_CREDITS = "OUT_OF_CREDITS"
    MODEL_REMOVED = "MODEL_REMOVED"
    AUTH_FAILED = "AUTH_FAILED"
    TIMEOUT = "TIMEOUT"
    OFFLINE = "OFFLINE"


# ─── Routing ─────────────────────────────────────────────────────────────

@dataclass
class RoutingRequest:
    """What the gateway needs to route a request."""
    virtual_model: str
    required_capabilities: ModelCapabilities
    privacy_policy: str = "REMOTE_ALLOWED"  # LOCAL_ONLY, REMOTE_ALLOWED, etc.
    trace_id: str = ""
    request_id: str = ""


@dataclass
class RoutingDecision:
    """Result of routing."""
    provider: str
    model: str
    base_url: str
    estimated_latency_ms: float
    cost_estimate: float
    reason: str
    trace_id: str = ""


# ─── Privacy ─────────────────────────────────────────────────────────────

class PrivacyPolicy(enum.Enum):
    LOCAL_ONLY = "LOCAL_ONLY"
    REMOTE_ALLOWED = "REMOTE_ALLOWED"
    REMOTE_ALLOWED_NO_SECRETS = "REMOTE_ALLOWED_NO_SECRETS"
    PUBLIC = "PUBLIC"


# ─── Telemetry ──────────────────────────────────────────────────────────

@dataclass
class GatewayTelemetry:
    """Per-request telemetry for Experience Compiler."""
    request_id: str
    trace_id: str
    virtual_model: str
    selected_provider: str
    selected_model: str
    route_ms: float
    ttft_ms: Optional[float] = None
    total_ms: Optional[float] = None
    max_stream_gap_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    retry_count: int = 0
    failure_reason: Optional[str] = None
    cancelled: bool = False
    tool_required: bool = False
    tool_valid: bool = False
    timestamp: float = field(default_factory=time.time)


# ─── Events ──────────────────────────────────────────────────────────────

@dataclass
class GatewayEvent:
    """Events emitted to EventStore."""
    event_type: str  # PROVIDER_HEALTH_CHANGED, REQUEST_ROUTED, REQUEST_COMPLETED, etc.
    trace_id: str
    payload: dict
    timestamp: float = field(default_factory=time.time)


# ─── Helper ──────────────────────────────────────────────────────────────

def get_virtual_model_config(name: str) -> Optional[dict]:
    """Get virtual model configuration."""
    return VIRTUAL_MODELS.get(name)


def validate_capabilities(required: ModelCapabilities, available: ModelCapabilities) -> bool:
    """Check if available capabilities satisfy requirements."""
    if required.tools and not available.tools:
        return False
    if required.vision and not available.vision:
        return False
    if required.json_schema and not available.json_schema:
        return False
    if required.context_tokens > available.context_tokens:
        return False
    return True


def map_provider_error(status_code: int, error_body: str = "") -> ProviderHealth:
    """Map HTTP status to provider health state."""
    if status_code == 401 or status_code == 403:
        return ProviderHealth.AUTH_FAILED
    if status_code == 402:
        return ProviderHealth.OUT_OF_CREDITS
    if status_code == 404:
        return ProviderHealth.MODEL_REMOVED
    if status_code == 410:
        return ProviderHealth.MODEL_REMOVED
    if status_code == 429:
        return ProviderHealth.RATE_LIMITED
    if status_code >= 500:
        return ProviderHealth.DEGRADED
    if status_code == 408 or status_code == 504:
        return ProviderHealth.TIMEOUT
    return ProviderHealth.DEGRADED


# ─── Virtual Model Aliases ──────────────────────────────────────────────

# These are what OpenCode will see in /v1/models
VIRTUAL_MODEL_ALIASES = {
    "hal/fast": "hal/fast",
    "hal/coder": "hal/coder",
    "hal/deep": "hal/deep",
    "hal/council": "hal/council",
    "council": "hal/council",
}

# OpenCode model config should reference these:
# "model": "hal/coder"