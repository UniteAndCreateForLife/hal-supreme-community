"""
HAL Model Gateway — Package Init
================================
"""
from __future__ import annotations

from .contracts import (
    VIRTUAL_MODELS,
    VIRTUAL_MODEL_ALIASES,
    ModelCapabilities,
    ProviderCapabilities,
    ProviderHealth,
    RoutingRequest,
    RoutingDecision,
    PrivacyPolicy,
    GatewayTelemetry,
    GatewayEvent,
)

from .registry import ProviderRegistry, get_registry, load_from_opencode_config
from .router import Router, FallbackChain, get_router
from .providers import ProviderAdapter, AdapterManager, AdapterRequest, AdapterResponse, create_adapter

__version__ = "1.0.0"


def __getattr__(name: str):
    if name == "app":
        from .server import app

        return app
    raise AttributeError(name)

__all__ = [
    # Contracts
    "VIRTUAL_MODELS",
    "VIRTUAL_MODEL_ALIASES",
    "ModelCapabilities",
    "ProviderCapabilities",
    "ProviderHealth",
    "RoutingRequest",
    "RoutingDecision",
    "PrivacyPolicy",
    "GatewayTelemetry",
    "GatewayEvent",
    # Registry
    "ProviderRegistry",
    "get_registry",
    "load_from_opencode_config",
    # Router
    "Router",
    "FallbackChain",
    "get_router",
    # Providers
    "ProviderAdapter",
    "AdapterManager",
    "AdapterRequest",
    "AdapterResponse",
    "create_adapter",
    # Server
    "app",
]
