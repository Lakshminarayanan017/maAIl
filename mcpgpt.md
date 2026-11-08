Yes. I understand exactly what you're aiming for, and I think this is an important architectural addition to Maail.

You want the agents to be independent of the actual tool implementations.

Instead of every agent directly importing Python functions or depending on specific integrations, agents should connect through an MCP (Model Context Protocol) layer. MCP servers expose reusable tools, and different agents can discover and use the tools they are authorized to access.

This is the loosely coupled architecture shown in your image.

I checked the uploaded Maail v3.0 HLD and LLD documents.

## 1. Does our existing HLD/LLD mention this?

The answer is: Partially, but not explicitly as MCP architecture.

Here's what already exists:

| Existing architecture | What it provides                                       |
| --------------------- | ------------------------------------------------------ |
| Agent Registry        | Defines agents and their permitted tool subsets        |
| Tool Registry         | Central registry of available tools                    |
| `ToolSpec`            | Tool metadata, arguments, results and permissions      |
| Provider Adapters     | Abstracts Gmail, GitHub and LLM providers              |
| Agent Runtime         | Executes tool calls and enforces budgets               |
| Shared services       | Allows multiple agents to reuse the same functionality |

The LLD even defines a `ToolSpec` with typed arguments, typed results, permission requirements and a handler function.&#x20;

03-lld-agent-runtime.md



The HLD also separates agents, runtime and provider adapters into different architectural layers.&#x20;

01-hld.md



But there's a crucial difference:

The existing design uses an internal Python tool registry. It doesn't explicitly define an MCP client, MCP server, protocol-based communication, remote tool discovery or independently deployable tool servers.

So we have tool abstraction, but not the MCP architecture you are proposing.

## 2. How I envision MCP in Maail

Let's use your diagram's concept, but adapt it to Maail.

\#chatgpt-mermaid-\_r_3ms\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_3ms\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3ms\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3ms\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_3ms\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3ms\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_3ms\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_3ms\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_3ms\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_3ms\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_3ms\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_3ms\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3ms\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3ms\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_3ms\_ p{margin:0;}#chatgpt-mermaid-\_r_3ms\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3ms\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3ms\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3ms\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_3ms\_ .label text,#chatgpt-mermaid-\_r_3ms\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3ms\_ .node rect,#chatgpt-mermaid-\_r_3ms\_ .node circle,#chatgpt-mermaid-\_r_3ms\_ .node ellipse,#chatgpt-mermaid-\_r_3ms\_ .node polygon,#chatgpt-mermaid-\_r_3ms\_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-\_r_3ms\_ .rough-node .label text,#chatgpt-mermaid-\_r_3ms\_ .node .label text,#chatgpt-mermaid-\_r_3ms\_ .image-shape .label,#chatgpt-mermaid-\_r_3ms\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_3ms\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_3ms\_ .rough-node .label,#chatgpt-mermaid-\_r_3ms\_ .node .label,#chatgpt-mermaid-\_r_3ms\_ .image-shape .label,#chatgpt-mermaid-\_r_3ms\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_3ms\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_3ms\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3ms\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3ms\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_3ms\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_3ms\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3ms\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3ms\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3ms\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_3ms\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_3ms\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3ms\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3ms\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_3ms\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3ms\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_3ms\_ .icon-shape,#chatgpt-mermaid-\_r_3ms\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3ms\_ .icon-shape p,#chatgpt-mermaid-\_r_3ms\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_3ms\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_3ms\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3ms\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_3ms\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_3ms\_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_3ms\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_3ms\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_3ms\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_3ms\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3ms\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_3ms\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3ms\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3ms\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3ms\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_3ms\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_3ms\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-\_r_3ms\_ .node rect,#chatgpt-mermaid-\_r_3ms\_ .node circle,#chatgpt-mermaid-\_r_3ms\_ .node ellipse,#chatgpt-mermaid-\_r_3ms\_ .node polygon,#chatgpt-mermaid-\_r_3ms\_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_3ms\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_3ms\_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_3ms\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_3ms\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3ms\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}REUSABLE TOOLSMCP SERVER LAYERAGENT RUNTIME / MCP CLIENT HOSTMAAIL AGENT LAYERget_thread / search_threadsearch_emails / filter_emailsget_issue / get_pull_requestget_events / find_slotscreate_task / get_deadlinesMail MCP ServerSearch MCP ServerGitHub MCP ServerCalendar MCP ServerProductivity MCP ServerAgent Tool RouterPermission and PolicyEnforcementMCP Client ManagerTriage AgentSummarizer AgentDeveloper AgentDeadline AgentCompanion AgentMCP ProtocolMCP ProtocolMCP ProtocolMCP ProtocolMCP Protocol

The important difference:

- Agents don't need to know how Gmail API works.
- Agents don't need to know how GitHub API works.
- Agents don't need to know how search is implemented.
- They only need access to the tools exposed by their authorized MCP servers.

The MCP servers own the integration-facing tool implementations.

### Example: Developer Agent

Suppose the Developer Agent needs to investigate a CI failure.

Its authorized tools might be:

```
Mail MCP Server
    ├── get_thread
    └── search_threads

GitHub MCP Server
    ├── get_repository
    ├── get_pull_request
    ├── get_issue
    └── get_workflow_run

Search MCP Server
    ├── search_emails
    └── search_threads
```

The Developer Agent can use these tools without knowing their internal implementation.

Now imagine we replace the GitHub integration with another version or add GitLab.

We can expose the appropriate tools through a different server without redesigning the Developer Agent.

That's the architectural benefit we want.

## 3. Why this makes Maail loosely coupled

Consider two approaches.

Approach A — Direct integration

```
Developer Agent ──> GitHub API
Companion Agent ──> GitHub API
Another Agent ────> GitHub API
```

Problems:

- Repeated integration logic.
- Multiple authentication implementations.
- Changes to the API affect multiple agents.
- Difficult to share tools consistently.

Approach B — MCP-based integration

```
Developer Agent ──┐
Companion Agent ──┼──> GitHub MCP Server ──> GitHub API
Other Agent ──────┘
```

Advantages:

1. Reusability: Multiple agents can use the same tools.
2. Loose coupling: Agents depend on tool contracts rather than API implementations.
3. Scalability: New tool servers can be introduced independently.
4. Extensibility: New integrations don't require modifying every agent.
5. Maintainability: Authentication, validation and integration logic can be centralized.
6. Permission control: Different agents can receive different tool subsets.

One important nuance: MCP gives us a standardized communication and tool interface. It does not automatically guarantee security, isolation or scalability. Maail's runtime must enforce those separately.

## 4. How many MCP servers should Maail have?

I would avoid creating one giant MCP server containing every tool.

Instead, use domain-oriented MCP servers.

| MCP server       | Tools it exposes                                  | Consumers            |
| ---------------- | ------------------------------------------------- | -------------------- |
| Mail MCP         | Thread retrieval, message details, sender history | Most agents          |
| Search MCP       | Email search, thread search, filtering            | Companion, Developer |
| GitHub MCP       | Repository, issue, PR, workflow retrieval         | Developer            |
| Calendar MCP     | Events, availability, schedules                   | Companion, Deadline  |
| Productivity MCP | Tasks, deadlines, reminders                       | Companion, Briefing  |

These are logical server boundaries initially. We don't need five separate deployments immediately.

We can start with one or two servers and expand when the integrations justify it.

## 5. An important security consideration

We must not let MCP accidentally bypass our existing three-plane architecture.

I recommend:

Plane U — Untrusted reading

Read-only Mail and Search tools. No external network access or side effects.

Plane C — Controlled reasoning

Approved read-only integrations such as GitHub retrieval. Can propose actions, but cannot execute them.

Plane X — Execution

No model-accessible MCP tools for sending or modifying external data. A separate deterministic executor handles approved actions.

Also:

- Authenticate MCP clients and servers.
- Scope every operation to the authenticated user.
- Validate tool arguments and results.
- Enforce timeouts and output-size limits.
- Use explicit allowlists per agent.
- Log tool calls and failures.
- Treat MCP server responses as potentially untrusted.
- Never allow a server to grant an agent additional capabilities by itself.

This preserves the existing security model in our LLD.&#x20;

03-lld-agent-runtime.md



## 6. What needs to change in our HLD and LLD?

I would formally introduce the following components.

| Document                     | Addition                                                                       |
| ---------------------------- | ------------------------------------------------------------------------------ |
| `01-hld.md`                  | MCP architecture layer and system context diagram                              |
| `03-lld-agent-runtime.md`    | MCP client manager, tool discovery, server registry, invocation lifecycle      |
| `04-lld-api-sync-modules.md` | MCP server deployment, configuration, authentication and connection management |
| `00-gap-analysis.md`         | MCP adoption tradeoffs, security and operational decisions                     |

### Proposed backend structure

```
backend/app/modules/
│
├── agents/
│   ├── runtime/
│   │   ├── orchestrator.py
│   │   ├── agent_registry.py
│   │   └── budget_manager.py
│   │
│   └── mcp/
│       ├── client_manager.py
│       ├── server_registry.py
│       ├── tool_discovery.py
│       ├── tool_router.py
│       └── permission_manager.py
│
├── mcp_servers/
│   ├── mail/
│   │   ├── server.py
│   │   └── tools/
│   ├── search/
│   │   ├── server.py
│   │   └── tools/
│   ├── github/
│   │   ├── server.py
│   │   └── tools/
│   └── productivity/
│       ├── server.py
│       └── tools/
│
├── providers/
│   ├── email/
│   ├── github/
│   └── llm/
│
└── executor/
    └── action_executor.py
```

This is a proposed logical layout; we can keep the initial MCP servers within the same repository and deployment.

## 7. One additional architectural distinction

There are three things we should not confuse:

| Component         | Responsibility                                 |
| ----------------- | ---------------------------------------------- |
| Agent             | Decides what it needs to accomplish            |
| MCP Client / Host | Discovers, filters and invokes permitted tools |
| MCP Server        | Exposes tools and handles their implementation |

The agent runtime should remain the central policy enforcement point. MCP servers should not independently decide which agents are authorized to use sensitive tools.

For Maail, I would use MCP's standardized server/client protocol and keep the transport replaceable. Local development could use STDIO; independently deployed servers could use Streamable HTTP.

## 8. My proposed architectural decision

Recommended for Maail v3.1

Adopt an MCP-based tool architecture with a centralized agent runtime and domain-oriented MCP servers.

The resulting system becomes:

\#chatgpt-mermaid-\_r_3oc\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_3oc\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3oc\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_3oc\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_3oc\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3oc\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_3oc\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_3oc\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_3oc\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_3oc\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_3oc\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_3oc\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3oc\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3oc\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_3oc\_ p{margin:0;}#chatgpt-mermaid-\_r_3oc\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3oc\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3oc\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3oc\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_3oc\_ .label text,#chatgpt-mermaid-\_r_3oc\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3oc\_ .node rect,#chatgpt-mermaid-\_r_3oc\_ .node circle,#chatgpt-mermaid-\_r_3oc\_ .node ellipse,#chatgpt-mermaid-\_r_3oc\_ .node polygon,#chatgpt-mermaid-\_r_3oc\_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-\_r_3oc\_ .rough-node .label text,#chatgpt-mermaid-\_r_3oc\_ .node .label text,#chatgpt-mermaid-\_r_3oc\_ .image-shape .label,#chatgpt-mermaid-\_r_3oc\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_3oc\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_3oc\_ .rough-node .label,#chatgpt-mermaid-\_r_3oc\_ .node .label,#chatgpt-mermaid-\_r_3oc\_ .image-shape .label,#chatgpt-mermaid-\_r_3oc\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_3oc\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_3oc\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3oc\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3oc\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_3oc\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_3oc\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3oc\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3oc\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3oc\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_3oc\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_3oc\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3oc\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3oc\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_3oc\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_3oc\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_3oc\_ .icon-shape,#chatgpt-mermaid-\_r_3oc\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_3oc\_ .icon-shape p,#chatgpt-mermaid-\_r_3oc\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_3oc\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_3oc\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_3oc\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_3oc\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_3oc\_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_3oc\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_3oc\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_3oc\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_3oc\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3oc\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_3oc\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_3oc\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3oc\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_3oc\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_3oc\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_3oc\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-\_r_3oc\_ .node rect,#chatgpt-mermaid-\_r_3oc\_ .node circle,#chatgpt-mermaid-\_r_3oc\_ .node ellipse,#chatgpt-mermaid-\_r_3oc\_ .node polygon,#chatgpt-mermaid-\_r_3oc\_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_3oc\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_3oc\_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_3oc\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_3oc\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_3oc\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}Maail Web ApplicationFastAPI BackendAgent OrchestratorAgent RegistryMCP Client ManagerPolicy and Permission GatewayMail MCPSearch MCPGitHub MCPProductivity MCPMail ServicesRetrieval ServicesGitHub AdapterTask ServicesPostgreSQLProposed ActionsHuman ApprovalPlane X ExecutorMCPMCPMCPMCP

One final implementation decision: MCP should be a first-class architectural boundary, but we should not turn every internal Python function into a remote MCP call. Pure internal operations can remain ordinary service calls. MCP is most valuable at reusable integration and tool-server boundaries.

That gives us loose coupling without unnecessary network hops and operational complexity.

I consider this a significant missing piece in the current HLD/LLD. We should update the architecture documents to explicitly include MCP rather than pretending the existing Python tool registry already provides it.