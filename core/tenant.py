"""Multi-tenant agent infrastructure — isolation, rate limiting, billing.

Ensures agents for Tenant A cannot access Tenant B's data, and
that one tenant's heavy usage doesn't starve others.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class TenantConfig:
    tenant_id: str
    name: str
    tier: str = "standard"  # free, standard, enterprise
    rate_limit_rpm: int = 60
    max_tokens_per_day: int = 100000
    custom_prompts: dict[str, str] = field(default_factory=dict)
    quality_threshold: float = 0.7
    agents_enabled: list[str] = field(default_factory=lambda: ["research", "analysis", "outreach"])


@dataclass
class UsageRecord:
    tenant_id: str
    agent: str
    tokens_used: int
    model: str
    cost_usd: float
    timestamp: float = field(default_factory=time.time)


class TenantRegistry:
    """Manages tenant configurations and access control."""

    def __init__(self):
        self._tenants: dict[str, TenantConfig] = {}

    def register(self, config: TenantConfig) -> TenantConfig:
        self._tenants[config.tenant_id] = config
        log.info(f"tenant registered: {config.tenant_id} ({config.tier})")
        return config

    def get(self, tenant_id: str) -> Optional[TenantConfig]:
        return self._tenants.get(tenant_id)

    def list_tenants(self) -> list[TenantConfig]:
        return list(self._tenants.values())


class NamespaceIsolation:
    """Ensures data isolation between tenants via key prefixing.
    In production: Pinecone namespaces, Redis key prefixes, scoped DB queries."""

    def __init__(self):
        self._store: dict[str, dict[str, Any]] = defaultdict(dict)

    def write(self, tenant_id: str, key: str, value: Any):
        ns_key = f"{tenant_id}:{key}"
        self._store[tenant_id][ns_key] = value

    def read(self, tenant_id: str, key: str) -> Optional[Any]:
        ns_key = f"{tenant_id}:{key}"
        return self._store.get(tenant_id, {}).get(ns_key)

    def list_keys(self, tenant_id: str) -> list[str]:
        prefix = f"{tenant_id}:"
        return [k.replace(prefix, "") for k in self._store.get(tenant_id, {}).keys()]

    def cross_tenant_check(self, tenant_a: str, tenant_b: str, key: str) -> bool:
        """Verify tenant A cannot read tenant B's data."""
        ns_key = f"{tenant_b}:{key}"
        return ns_key not in self._store.get(tenant_a, {})


class RateLimiter:
    """Per-tenant rate limiting using sliding window."""

    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, tenant_id: str, rpm_limit: int) -> bool:
        """Returns True if request is allowed, False if rate-limited."""
        now = time.time()
        window = self._windows[tenant_id]

        # Prune entries older than 60 seconds
        self._windows[tenant_id] = [t for t in window if now - t < 60]

        if len(self._windows[tenant_id]) >= rpm_limit:
            log.warning(f"RATE LIMITED: {tenant_id} ({len(self._windows[tenant_id])}/{rpm_limit} rpm)")
            return False

        self._windows[tenant_id].append(now)
        return True


class BillingTracker:
    """Tracks per-tenant LLM token usage and cost."""

    MODEL_COSTS = {
        "gpt-4o": 0.005,      # $ per 1K tokens
        "gpt-4o-mini": 0.0002,
        "claude-sonnet": 0.003,
        "mistral-7b": 0.0001,
    }

    def __init__(self):
        self._records: list[UsageRecord] = []
        self._daily_usage: dict[str, int] = defaultdict(int)

    def record(self, tenant_id: str, agent: str, tokens: int, model: str):
        cost = tokens / 1000 * self.MODEL_COSTS.get(model, 0.001)
        self._records.append(UsageRecord(
            tenant_id=tenant_id, agent=agent,
            tokens_used=tokens, model=model, cost_usd=round(cost, 6),
        ))
        self._daily_usage[tenant_id] += tokens

    def get_usage(self, tenant_id: str) -> dict:
        records = [r for r in self._records if r.tenant_id == tenant_id]
        total_tokens = sum(r.tokens_used for r in records)
        total_cost = sum(r.cost_usd for r in records)
        by_agent = defaultdict(int)
        for r in records:
            by_agent[r.agent] += r.tokens_used
        return {
            "tenant": tenant_id,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "by_agent": dict(by_agent),
            "requests": len(records),
        }

    def check_budget(self, tenant_id: str, daily_limit: int) -> bool:
        """Returns True if tenant is within daily token budget."""
        return self._daily_usage.get(tenant_id, 0) < daily_limit

    def get_all_usage(self) -> dict[str, dict]:
        tenants = set(r.tenant_id for r in self._records)
        return {t: self.get_usage(t) for t in tenants}


class MultiTenantPlatform:
    """Unified platform combining all multi-tenant components."""

    def __init__(self):
        self.registry = TenantRegistry()
        self.isolation = NamespaceIsolation()
        self.rate_limiter = RateLimiter()
        self.billing = BillingTracker()

    def process_request(self, tenant_id: str, agent: str,
                        tokens: int = 500, model: str = "gpt-4o") -> dict:
        """Process an agent request with full tenant isolation and billing."""
        tenant = self.registry.get(tenant_id)
        if not tenant:
            return {"error": "tenant_not_found", "tenant_id": tenant_id}

        # Rate limit check
        if not self.rate_limiter.check(tenant_id, tenant.rate_limit_rpm):
            return {"error": "rate_limited", "tenant_id": tenant_id}

        # Budget check
        if not self.billing.check_budget(tenant_id, tenant.max_tokens_per_day):
            return {"error": "budget_exceeded", "tenant_id": tenant_id}

        # Agent enabled check
        if agent not in tenant.agents_enabled:
            return {"error": "agent_not_enabled", "agent": agent, "tenant_id": tenant_id}

        # Record usage
        self.billing.record(tenant_id, agent, tokens, model)

        return {
            "status": "ok",
            "tenant_id": tenant_id,
            "agent": agent,
            "tokens": tokens,
            "model": model,
        }
