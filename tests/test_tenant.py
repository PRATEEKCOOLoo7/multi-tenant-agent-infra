import pytest
from core.tenant import (
    MultiTenantPlatform, TenantConfig, TenantRegistry,
    NamespaceIsolation, RateLimiter, BillingTracker,
)

class TestIsolation:
    def test_write_and_read(self):
        ns = NamespaceIsolation()
        ns.write("t1", "key", "value")
        assert ns.read("t1", "key") == "value"

    def test_cross_tenant_blocked(self):
        ns = NamespaceIsolation()
        ns.write("t1", "secret", "data")
        assert ns.read("t2", "secret") is None

    def test_cross_tenant_check(self):
        ns = NamespaceIsolation()
        ns.write("t1", "data", "value")
        assert ns.cross_tenant_check("t2", "t1", "data")

    def test_list_keys(self):
        ns = NamespaceIsolation()
        ns.write("t1", "a", 1)
        ns.write("t1", "b", 2)
        keys = ns.list_keys("t1")
        assert "a" in keys and "b" in keys

class TestRateLimiter:
    def test_allows_under_limit(self):
        rl = RateLimiter()
        assert rl.check("t1", 10)

    def test_blocks_over_limit(self):
        rl = RateLimiter()
        for _ in range(10):
            rl.check("t1", 10)
        assert not rl.check("t1", 10)

    def test_independent_tenants(self):
        rl = RateLimiter()
        for _ in range(10):
            rl.check("t1", 10)
        assert rl.check("t2", 10)  # t2 unaffected

class TestBilling:
    def test_record_and_query(self):
        b = BillingTracker()
        b.record("t1", "research", 1000, "gpt-4o")
        usage = b.get_usage("t1")
        assert usage["total_tokens"] == 1000
        assert usage["total_cost_usd"] > 0

    def test_budget_check(self):
        b = BillingTracker()
        b.record("t1", "research", 50000, "gpt-4o")
        assert b.check_budget("t1", 100000)  # under limit
        assert not b.check_budget("t1", 40000)  # over limit

    def test_by_agent_breakdown(self):
        b = BillingTracker()
        b.record("t1", "research", 500, "gpt-4o")
        b.record("t1", "outreach", 300, "gpt-4o")
        usage = b.get_usage("t1")
        assert usage["by_agent"]["research"] == 500
        assert usage["by_agent"]["outreach"] == 300

class TestPlatform:
    def setup_method(self):
        self.p = MultiTenantPlatform()
        self.p.registry.register(TenantConfig("t1", "TestCo", rate_limit_rpm=100, max_tokens_per_day=100000))
        self.p.registry.register(TenantConfig("t2", "Other", agents_enabled=["research"]))

    def test_successful_request(self):
        r = self.p.process_request("t1", "research", 500, "gpt-4o")
        assert r["status"] == "ok"

    def test_unknown_tenant(self):
        r = self.p.process_request("unknown", "research")
        assert r["error"] == "tenant_not_found"

    def test_agent_not_enabled(self):
        r = self.p.process_request("t2", "outreach")
        assert r["error"] == "agent_not_enabled"

    def test_billing_tracked(self):
        self.p.process_request("t1", "research", 800, "gpt-4o")
        usage = self.p.billing.get_usage("t1")
        assert usage["total_tokens"] == 800
