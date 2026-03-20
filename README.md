# Multi-Tenant Agent Infrastructure

Production infrastructure layer for deploying AI agents at scale across multiple tenants (customers). Handles tenant isolation, resource allocation, rate limiting, cost attribution, and horizontal scaling — so agents for Customer A can't see Customer B's data or consume Customer B's compute budget.

## Why Multi-Tenancy Matters for Agent Platforms

When you're selling an agentic platform to 40+ enterprise customers (not building an internal tool), single-tenant architecture breaks immediately:

| Problem | What Happens | This Repo's Solution |
|---|---|---|
| Data leakage | Agent trained on Customer A's CRM data generates outreach using Customer B's contacts | Tenant-scoped memory, vector stores, and context |
| Noisy neighbor | Customer A's 10,000-contact batch job starves Customer B's real-time outreach agent | Per-tenant rate limits, priority queues, resource quotas |
| Cost attribution | Who's paying for these GPU-hours? | Per-tenant token counting, LLM cost tracking, billing events |
| Config drift | Customer A wants aggressive outreach tone, Customer B wants conservative | Per-tenant agent config, prompt templates, quality gate thresholds |
| Scaling | 5 tenants → 500 tenants without redeploying | Horizontal pod autoscaling, shared compute with isolation |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    MULTI-TENANT AGENT PLATFORM                   │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                      │
│  │ Tenant A │  │ Tenant B │  │ Tenant C │   ... Tenant N       │
│  │ Config   │  │ Config   │  │ Config   │                      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                      │
│       │              │              │                            │
│       ▼              ▼              ▼                            │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  ROUTING LAYER                           │    │
│  │  • Tenant identification (API key → tenant_id)          │    │
│  │  • Rate limiting (per-tenant, per-agent)                │    │
│  │  • Priority queue (paid tier > free tier)               │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │                  COMPUTE LAYER                           │    │
│  │  Shared agent workers with tenant-scoped execution       │    │
│  │  • Agent pods scale horizontally                        │    │
│  │  • Each execution carries tenant_id context             │    │
│  │  • GPU pool with fair-share scheduling                  │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │                  DATA LAYER (Isolated)                    │    │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐                 │    │
│  │  │ VectorDB│  │  Redis  │  │   CRM   │  Per-tenant     │    │
│  │  │ (namespaced) │ (prefixed) │ (scoped)│  namespaces    │    │
│  │  └─────────┘  └─────────┘  └─────────┘                 │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  BILLING & OBSERVABILITY                  │    │
│  │  • Per-tenant LLM token usage tracking                  │    │
│  │  • Per-tenant agent action counts                       │    │
│  │  • Cost attribution and billing events                  │    │
│  │  • Per-tenant quality dashboards                        │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## Key Features

### Tenant Isolation
- **Namespace-scoped vector stores**: Each tenant's embeddings in a separate Pinecone namespace — zero cross-contamination
- **Prefixed Redis keys**: All cache and state keys prefixed with tenant_id
- **Scoped CRM connections**: Each tenant's Salesforce/HubSpot credentials stored and accessed separately
- **Memory isolation**: Agent memory system scoped to tenant — Agent memory from Tenant A is invisible to Tenant B

### Resource Management
- **Per-tenant rate limits**: Configurable requests/minute and tokens/day per tenant
- **Priority queues**: Enterprise tier gets priority over free tier during peak load
- **Fair-share GPU scheduling**: Prevents one tenant from monopolizing GPU resources
- **Burst capacity**: Tenants can burst above their quota temporarily with automatic throttling

### Cost Attribution
- **Token-level tracking**: Every LLM call tagged with tenant_id, agent_id, model used, tokens consumed
- **Cost aggregation**: Real-time per-tenant cost dashboards
- **Billing events**: Emits billing events for integration with Stripe/payment systems
- **Budget alerts**: Notify tenant admins when approaching usage limits

### Per-Tenant Configuration
- **Custom prompt templates**: Each tenant can customize agent prompts for their brand voice
- **Quality gate thresholds**: Tenant A might want strict compliance checking, Tenant B might want faster throughput
- **Agent scheduling**: Different heartbeat intervals per tenant based on their plan
- **Feature flags**: Enable/disable agent capabilities per tenant

## Project Structure

```
multi-tenant-agent-infra/
├── README.md
├── requirements.txt
├── routing/
│   ├── __init__.py
│   ├── tenant_router.py         # API key → tenant_id resolution
│   ├── rate_limiter.py          # Per-tenant rate limiting
│   └── priority_queue.py        # Tier-based priority scheduling
├── isolation/
│   ├── __init__.py
│   ├── namespace_manager.py     # Vector DB namespace scoping
│   ├── state_isolation.py       # Redis key prefixing
│   ├── credential_vault.py      # Per-tenant secret management
│   └── memory_scope.py          # Agent memory tenant isolation
├── compute/
│   ├── __init__.py
│   ├── worker_pool.py           # Horizontal agent worker scaling
│   ├── gpu_scheduler.py         # Fair-share GPU allocation
│   └── autoscaler.py            # Load-based pod autoscaling
├── billing/
│   ├── __init__.py
│   ├── token_tracker.py         # Per-tenant LLM usage tracking
│   ├── cost_aggregator.py       # Real-time cost dashboards
│   ├── billing_events.py        # Stripe integration events
│   └── budget_alerts.py         # Usage limit notifications
├── config/
│   ├── __init__.py
│   ├── tenant_config.py         # Per-tenant configuration management
│   └── feature_flags.py         # Per-tenant feature toggles
├── tests/
│   ├── test_isolation.py        # Verify no cross-tenant data leakage
│   ├── test_rate_limiting.py
│   ├── test_billing.py
│   └── test_priority.py
└── examples/
    └── deploy_multi_tenant.py
```

## Design Decisions

- **Shared compute, isolated data**: Running separate agent clusters per tenant doesn't scale past 10 tenants. Shared workers with tenant-scoped data is the standard SaaS pattern. The isolation layer ensures safety without the cost of dedicated infrastructure.
- **Namespace over database-per-tenant**: Pinecone namespaces and Redis key prefixes provide sufficient isolation without the operational overhead of separate database instances per tenant. For tenants with strict compliance requirements (healthcare, finance), offer dedicated namespace with encryption at rest.
- **Token-level billing, not action-level**: Different agents use different amounts of LLM tokens. Billing by token gives accurate cost attribution. Action-level billing (per email sent, per lead scored) is built on top as a business logic layer.

