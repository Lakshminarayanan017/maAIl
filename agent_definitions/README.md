# agent_definitions — procedural memory

Agent manifests. One YAML per agent: plane, tier, model class, tool allowlist, context
requirements, token and step budgets, output schema reference.

**Git is the store.** These files are read at deploy, never written at runtime. A runtime
write here is a prompt-injection vector that survives restarts, not a feature — the same
reason `procedures/`, `prompts/` and `tool_contracts/` are read-only too.

Enforced by `backend/tests/arch/test_no_runtime_writes.py`.

See [docs/architecture/05-memory.md](../docs/architecture/05-memory.md) §1 and
[03-lld-agent-runtime.md](../docs/architecture/03-lld-agent-runtime.md).

Populated in phase 5.
