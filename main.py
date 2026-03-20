"""Multi-Tenant Agent Infrastructure — Demo"""
import logging
from core.tenant import MultiTenantPlatform, TenantConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s: %(message)s", datefmt="%H:%M:%S")

def main():
    print(f"\n{'='*60}")
    print("  Multi-Tenant Agent Infrastructure — Demo")
    print(f"{'='*60}")

    platform = MultiTenantPlatform()

    # Register tenants
    platform.registry.register(TenantConfig("t_acme", "Acme Corp", "enterprise", rate_limit_rpm=100, max_tokens_per_day=500000))
    platform.registry.register(TenantConfig("t_startup", "SmallCo", "standard", rate_limit_rpm=30, max_tokens_per_day=50000))
    platform.registry.register(TenantConfig("t_free", "FreeTier", "free", rate_limit_rpm=10, max_tokens_per_day=5000, agents_enabled=["research"]))

    # Data isolation
    print(f"\n--- Data Isolation ---")
    platform.isolation.write("t_acme", "contacts", ["Sarah Chen", "David Kim"])
    platform.isolation.write("t_startup", "contacts", ["Jane Doe"])

    acme_data = platform.isolation.read("t_acme", "contacts")
    cross_check = platform.isolation.cross_tenant_check("t_startup", "t_acme", "contacts")
    print(f"  Acme reads own data: {acme_data}")
    print(f"  Startup cannot read Acme: {cross_check}")

    # Process requests
    print(f"\n--- Request Processing ---")
    for tenant, agent, tokens in [
        ("t_acme", "research", 800), ("t_acme", "analysis", 600), ("t_acme", "outreach", 400),
        ("t_startup", "research", 500), ("t_startup", "outreach", 300),
        ("t_free", "research", 200), ("t_free", "outreach", 100),  # outreach not enabled
    ]:
        result = platform.process_request(tenant, agent, tokens)
        status = result.get("status", result.get("error"))
        print(f"  {tenant:12s} {agent:10s} → {status}")

    # Billing
    print(f"\n--- Billing ---")
    for tenant_id, usage in platform.billing.get_all_usage().items():
        print(f"  {tenant_id}: {usage['total_tokens']} tokens, ${usage['total_cost_usd']:.4f}, {usage['requests']} requests")
        for agent, tokens in usage["by_agent"].items():
            print(f"    {agent}: {tokens} tokens")

    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    main()
