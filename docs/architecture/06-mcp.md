# Maail LLD — MCP Architecture

## 1. The honest case for MCP

The source proposal argues for MCP on **internal decoupling** — agents shouldn't import
Gmail code directly. That argument is weak here, because v3.0 already solves it: `ToolSpec`
gives typed args, typed results, permission metadata and a handler, and the `EmailProvider`
Protocol already lets you swap Gmail for Outlook without touching an agent. Wrapping that in
a protocol boundary adds serialisation, transport, auth and latency for a benefit you have.

The **strong** arguments, which the source material misses, are:

1. **Consuming third-party servers.** GitHub, Calendar and others ship maintained MCP
   servers. Using one is less code than writing an adapter, and someone else maintains it.
2. **Exposing Maail's own servers.** If `mail` and `search` are real MCP servers, the user
   can query their own mail from any MCP client. That is a genuine product capability with no
   alternative implementation.

Both arguments are about **crossing the process boundary with someone else's code** — in
either direction. That is what MCP is for. Internal decoupling is a side benefit.

### The resulting decision

> **MCP is a contract boundary in v1, not a transport.**
> Every tool is defined as an MCP-shaped contract. Servers run **in-process over an
> in-memory transport**. Transport is a config flag per server.

This buys the architecture, the loose coupling, the catalog and discovery semantics, and the
ability to lift any server to STDIO or Streamable HTTP later — without paying a network hop
inside the request path on day one, and without five deployments to operate before there are
five users.

```python
MCP_SERVERS = {
  "mail":         {"transport": "inprocess"},
  "search":       {"transport": "inprocess"},
  "memory":       {"transport": "inprocess"},
  "productivity": {"transport": "inprocess"},
  "github":       {"transport": "inprocess"},   # → "http" when swapped for a 3rd-party server
}
```

Changing one value moves a server out of process. No agent changes.

## 2. Server topology

Domain-oriented, as proposed. Logical boundaries in v1, deployable later.

| Server | Tools | Plane | Consumers |
|---|---|---|---|
| `mail` | `get_thread`, `get_message`, `get_sender_history` | U | most agents |
| `search` | `search_threads`, `search_messages` | U | Companion, Developer, Opportunity |
| `memory` | `search_episodes`, `get_user_facts`, `get_procedure`, `propose_memory_update` | U / C | per `05-memory.md` §3 |
| `productivity` | `query_deadlines`, `query_action_items`, `query_tasks` | C | Briefing, Companion |
| `github` | `get_repository`, `get_pull_request`, `get_issue`, `get_workflow_run` | C | Developer |

`calendar` is **not** in this list. Calendar is deferred in v1 scope (`01-hld.md` §6) and a
server for a deferred integration is dead code.

Plane X operations — draft, send, label, task creation — are **not MCP tools at all**. They
are executor functions reachable only through an approved `proposed_action`. No MCP server
exposes a side effect. This is what keeps invariant 2 intact once a protocol boundary exists.

## 3. Tool catalog and schema pinning

One catalog, Maail-owned metadata, keyed by server namespace plus schema hash.

```python
@dataclass(frozen=True)
class CatalogEntry:
    server_ns: str
    tool_name: str
    schema_hash: str            # sha256 of the declared input+output schema
    input_schema: dict          # JSON Schema, from the server
    output_schema: dict
    # --- Maail-owned. NEVER read from the server. ---
    plane: Literal["U", "C"]
    side_effect: bool
    network_egress: bool
    requires_capability: str | None
    max_result_bytes: int
    trust: Literal["first_party", "external"]
```

### Why the metadata is Maail-owned

A server declaring its own permissions is a server granting itself permissions. The source
material says "MCP servers should not independently decide which agents are authorized" —
correct, and the mechanism is this: **plane, capability and egress come from Maail's config,
keyed by `(server_ns, tool_name)`.** A server's own claims about its safety are ignored.

### Schema pinning — the rug-pull defence

Neither source document mentions this, and it is the main new hazard MCP introduces.

A server can change its tool definitions between discoveries. For an external server you do
not control, that is a live attack surface: today `get_issue` reads an issue; tomorrow its
description says something else, and **tool descriptions enter the model's prompt**.

```python
async def discover(server_ns: str) -> list[CatalogEntry]:
    tools = await client(server_ns).list_tools()
    for t in tools:
        h = sha256_schema(t)
        pinned = PINS.get((server_ns, t.name))
        if pinned is None:
            if TRUST[server_ns] == "external":
                raise UnapprovedTool(server_ns, t.name)   # explicit approval required
            PINS[(server_ns, t.name)] = h
        elif pinned != h:
            raise SchemaDrift(server_ns, t.name)          # fail closed, never auto-accept
    return build_entries(tools)
```

Pins live in `tool_contracts/<server>/<tool>.json` in Git, so a schema change is a reviewed
commit. Discovery runs at startup and on explicit refresh — never per turn.

### Tool poisoning

Tool **descriptions** from an external server are untrusted text that reaches the prompt. So:

- First-party descriptions come from Git, not from the running server.
- External descriptions are stored at approval time and served from the pin, not re-read.
- An external server's result is always Plane U content, regardless of which plane the tool
  sits in — the same ping-pong rule as GitHub in `03-lld-agent-runtime.md` §5.

## 4. Per-agent filtering

The harness concern: forty tools across five servers is forty schemas in every prompt.

```
Agent run requested
   │
   ├─ load agent manifest            (Git: agent_definitions/<id>.yaml)
   ├─ intersect: manifest.allowed_tools ∩ catalog
   ├─ drop anything violating the agent's plane        ← hard failure, not a filter
   ├─ drop anything whose capability is not granted
   ├─ task-narrow (manifest may scope by task kind)
   └─ emit only those schemas into the request
```

Manifest excerpt:

```yaml
id: developer
version: "1.0.0"
plane: U            # extract pass; the plan pass runs as a separate C-plane step
mcp:
  servers: [mail, search, github]
  allowed_tools:
    - mail/get_thread
    - search/search_threads
    - github/get_pull_request
    - github/get_issue
  max_tool_calls: 6
  max_result_bytes: 16000
```

Caching: schemas are built once per `(agent_id, agent_version, catalog_version)` and reused.
No rediscovery per turn, no schema reconstruction per request.

**Acceptance gate:** a Plane U agent must not be able to *discover* — not merely invoke — a
Plane C or X capability. Filtering happens before schemas are emitted, so an unauthorised
tool is not in the model's context at all. Asserted by the registry validation test.

## 5. Invocation lifecycle

```
agent emits tool_call(server_ns/tool_name, args)
   │
   ├─ in agent manifest?                  no → PlaneViolation (defence in depth)
   ├─ schema hash matches pin?             no → SchemaDrift, fail run
   ├─ validate args against input_schema   no → ToolArgError, returned to agent
   ├─ capability granted for this user?    no → CapabilityDenied
   ├─ budget check (calls, bytes, time)    no → CapExceeded
   │
   ├─ invoke with timeout + user context (RLS applies inside the handler)
   │
   ├─ validate result against output_schema
   ├─ truncate to max_result_bytes, record the truncation
   ├─ if trust == external → tag result as Plane U content
   └─ record agent_step (args + result DIGEST, never raw body text)
```

Every step is a named failure mode with a recorded outcome. Nothing is best-effort.

## 6. Module layout

```
backend/app/modules/
├── mcp/
│   ├── client_manager.py      # connections, sessions, timeouts, retries
│   ├── transports/
│   │   ├── inprocess.py       # v1 default — direct call, no serialization cost
│   │   ├── stdio.py           # local external servers
│   │   └── http.py            # Streamable HTTP for deployed/remote servers
│   ├── catalog.py             # CatalogEntry, discovery, schema pinning
│   ├── filter.py              # per-agent tool filtering
│   └── invoke.py              # the §5 lifecycle
│
├── mcp_servers/
│   ├── mail/        server.py  tools/
│   ├── search/      server.py  tools/
│   ├── memory/      server.py  tools/
│   ├── productivity/server.py  tools/
│   └── github/      server.py  tools/
│
├── providers/                 # unchanged — servers call these
│   ├── email/   base.py  gmail.py
│   ├── vcs/     base.py  github.py
│   └── llm/     base.py
└── executor/                  # Plane X. Not reachable from any MCP server.
```

Two CI-enforced rules:

- `mcp_servers/**` may import `providers/**` and `modules/<service>/**`, but **never**
  `executor/**` and never `agents/**`.
- `agents/**` may import `mcp/**` but **never** `providers/**` or `mcp_servers/**` — agents
  reach tools only through the client. This is the loose coupling, made mechanical.

## 7. What MCP does not give you

Worth stating plainly, because the source material's enthusiasm elides it:

| MCP provides | MCP does not provide |
|---|---|
| A standard tool contract and discovery | Authorisation — Maail's runtime owns that |
| Transport interoperability | Isolation — in-process means shared memory |
| A catalog shape | Trust — server output is still untrusted |
| Client/server decoupling | Scalability — that is still your deployment problem |
| Third-party interop | Safety — a side-effect tool is dangerous either way |

MCP is interoperability. The plane model, the budget manager and the executor are what make
Maail safe, and they would be required with or without it.

## 8. Triggers for moving a server out of process

| Trigger | Action |
|---|---|
| Replacing `github` with a maintained third-party server | → `stdio` or `http`, `trust: external` |
| Exposing `mail`/`search` to external MCP clients | → `http` with its own auth, read-only |
| A server needs a different runtime or language | → `stdio` |
| A server's dependencies conflict | → separate process |
| Nothing above applies | **stay in-process** |

The last row is the default and is expected to hold through v1.
