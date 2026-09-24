"""
HAL Model Gateway — Router
==========================

Fast capability-based router. No LLM call for routing.
Uses: virtual model contract + cached provider health + requirements.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

from hal_model_gateway.contracts import (
    ProviderCapabilities,
    ModelCapabilities,
    RoutingRequest,
    RoutingDecision,
    PrivacyPolicy,
    VIRTUAL_MODELS,
    get_virtual_model_config,
    validate_capabilities,
)
from hal_model_gateway.registry import ProviderRegistry, ProviderHealth, get_registry


if TYPE_CHECKING:
    from .registry import ProviderRegistry


@dataclass
class RouterMetrics:
    """Router performance tracking."""
    total_requests: int = 0
    routing_ms_sum: float = 0.0
    routing_ms_max: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    
    def record(self, elapsed_ms: float):
        self.total_requests += 1
        self.routing_ms_sum += elapsed_ms
        self.routing_ms_max = max(self.routing_ms_max, elapsed_ms)
        # Simple percentiles (would use proper reservoir in production)
        self.p50 = self.routing_ms_sum / self.total_requests
        self.p95 = max(self.p95, elapsed_ms)


class Router:
    """
    Fast capability-based router.
    
    No LLM call for routing. Uses:
    - Virtual model contract
    - Cached provider health
    - Required capabilities
    - Privacy policy
    - Latency/cost/quality tradeoffs
    
    Target: p50 < 5ms, p95 < 20ms
    """
    
    def __init__(self, registry: "ProviderRegistry"):
        self.registry = registry
        self._metrics = RouterMetrics()
    
    def route(self, request: "RoutingRequest") -> "RoutingDecision":
        """
        Select best provider for request.
        
        Algorithm:
        1. Get virtual model contract
        2. Filter providers by: health, capabilities, privacy
        3. Score by: latency, quality, cost, availability
        4. Return best match
        """
        start = time.perf_counter()
        
        # 1. Get virtual model config
        vconfig = get_virtual_model_config(request.virtual_model)
        if not vconfig:
            return RoutingDecision(
                provider="",
                model="",
                base_url="",
                estimated_latency_ms=0,
                cost_estimate=0.0,
                reason=f"Unknown virtual model: {request.virtual_model}",
            )
        
        # 2. Merge virtual model requirements with request requirements
        required = self._merge_requirements(vconfig, request)
        
        # 3. Get candidate providers
        candidates = self._get_candidates(required, request.privacy_policy)
        
        if not candidates:
            return RoutingDecision(
                provider="",
                model="",
                base_url="",
                estimated_latency_ms=0,
                cost_estimate=0.0,
                reason=f"No eligible providers for {request.virtual_model}",
            )
        
        # 4. Score and select
        best = self._score_and_select(candidates, required)
        
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._metrics.record(elapsed_ms)
        
        if best:
            return RoutingDecision(
                provider=best.provider,
                model=best.model,
                base_url=best.base_url,
                estimated_latency_ms=best.p50_latency_ms,
                cost_estimate=best.cost_per_1k_tokens,
                reason=f"Selected {best.provider}/{best.model} for {request.virtual_model}",
            )
        else:
            return RoutingDecision(
                provider="",
                model="",
                base_url="",
                estimated_latency_ms=0,
                cost_estimate=0.0,
                reason=f"No suitable provider after scoring",
            )
    
    def _merge_requirements(self, vconfig: dict, request: "RoutingRequest") -> ModelCapabilities:
        """Merge virtual model defaults with request-specific requirements."""
        v_caps = vconfig.get("capabilities", {})
        r_caps = request.required_capabilities
        
        return ModelCapabilities(
            context_tokens=max(v_caps.get("context_tokens", 4096), r_caps.context_tokens),
            tools=v_caps.get("tools", False) or r_caps.tools,
            vision=v_caps.get("vision", False) or r_caps.vision,
            json_schema=v_caps.get("json_schema", False) or r_caps.json_schema,
            streaming=v_caps.get("streaming", True),
            max_output_tokens=r_caps.max_output_tokens or 4096,
        )
    
    def _get_candidates(self, required: ModelCapabilities, privacy: str) -> list:
        """Filter providers by health, capabilities, and privacy."""
        candidates = []
        
        for provider_name, models in self.registry._providers.items():
            for model_name, caps in models.items():
                # Health check
                health = self.registry._health.get(provider_name, {}).get(model_name)
                if not health or health.health not in ("AVAILABLE", "DEGRADED"):
                    continue
                
                # Capability check
                if not validate_capabilities(required, caps.capabilities):
                    continue
                
                # Privacy check
                if not self._privacy_allows(caps, privacy):
                    continue
                
                candidates.append(caps)
        
        return candidates
    
    def _privacy_allows(self, caps: ProviderCapabilities, policy: str) -> bool:
        """Check if provider satisfies privacy policy."""
        if policy == "LOCAL_ONLY":
            return caps.local
        if policy == "REMOTE_ALLOWED":
            return True  # Both local and remote allowed
        if policy == "REMOTE_ALLOWED_NO_SECRETS":
            return True  # Both allowed, but caller should sanitize
        if policy == "PUBLIC":
            return True
        return True  # Default allow
    
    @staticmethod
    def cloud_first_enabled() -> bool:
        """HAL_CLOUD_FIRST env toggle (default ON). Set 0/false/off to restore legacy local bias."""
        v = str(os.environ.get("HAL_CLOUD_FIRST", "1")).strip().lower()
        return v not in ("0", "false", "no", "off")

    def _score_and_select(self, candidates: list, required: ModelCapabilities) -> Optional[Any]:
        """Score candidates and return best.

        When HAL_CLOUD_FIRST is enabled (default): prefer healthy non-local
        (cloud) providers; Ollama/local is last-resort only if no remote candidate.
        """
        if not candidates:
            return None

        cloud_first = self.cloud_first_enabled()
        pool = candidates
        if cloud_first:
            remote = [c for c in candidates if not getattr(c, "local", False)]
            if remote:
                pool = remote  # hard prefer cloud when any remote is eligible

        scored = []
        for caps in pool:
            # Scoring weights
            score = 0.0

            # Quality (0-1, higher better)
            score += caps.estimated_quality * 40

            # Latency (lower better, inverse)
            latency_score = max(0, 30 - (caps.p50_latency_ms / 1000) * 5)
            score += latency_score

            # Cost (lower better)
            cost_score = max(0, 20 - caps.cost_per_1k_tokens * 1000)
            score += cost_score

            # Availability bonus
            health = self.registry._health.get(caps.provider, {}).get(caps.model)
            if health and health.health == "AVAILABLE":
                score += 10
            elif health and health.health == "DEGRADED":
                score += 5

            if cloud_first:
                # Extra cloud bias within the (already remote-preferred) pool
                if not getattr(caps, "local", False):
                    score += 25
                else:
                    score -= 50
            else:
                # Legacy: local preference for privacy-sensitive
                if caps.local:
                    score += 5

            scored.append((score, caps))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1] if scored else None
    
    def get_metrics(self) -> dict:
        return {
            "total_requests": self._metrics.total_requests,
            "avg_routing_ms": self._metrics.routing_ms_sum / max(1, self._metrics.total_requests),
            "max_routing_ms": self._metrics.routing_ms_max,
            "p50_ms": self._metrics.p50,
            "p95_ms": self._metrics.p95,
        }


# ─── Fallback Chain ──────────────────────────────────────────────────────

class FallbackChain:
    """
    Manages provider fallback chain for a virtual model.
    
    Rules:
    - Failover BEFORE first output token: allowed
    - After first output token: NO splicing, abort/restart
    - Never merge partial tool calls from different providers
    """
    
    def __init__(self, registry: "ProviderRegistry", router: Router):
        self.registry = registry
        self.router = router
    
    def get_fallback_chain(self, request: "RoutingRequest") -> list:
        """Get ordered list of providers to try."""
        # Primary route
        primary = self.router.route(request)
        
        if not primary.provider:
            return []
        
        # Get alternatives (same capability, different provider)
        alternatives = []
        for provider_name, models in self.registry._providers.items():
            if provider_name == primary.provider:
                continue
            for model_name, caps in models.items():
                health = self.registry._health.get(provider_name, {}).get(model_name)
                if health and health.health in ("AVAILABLE", "DEGRADED"):
                    if validate_capabilities(request.required_capabilities, caps.capabilities):
                        alternatives.append(caps)
        
        # Sort: cloud-first puts local last; else quality desc
        if Router.cloud_first_enabled():
            alternatives.sort(
                key=lambda c: (getattr(c, "local", False), -float(getattr(c, "estimated_quality", 0.0)))
            )
        else:
            alternatives.sort(key=lambda c: c.estimated_quality, reverse=True)

        return [primary] + alternatives


# ─── Singleton ──────────────────────────────────────────────────────────

_router: Optional["Router"] = None

def get_router(registry: "ProviderRegistry" = None) -> Router:
    global _router
    if _router is None:
        if registry is None:
            from .registry import get_registry
            registry = get_registry()
        _router = Router(registry)
    return _router