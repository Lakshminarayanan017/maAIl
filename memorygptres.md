# Maail — Agentic Memory Architecture Review



Added to architecture review

Memory engineering



Yes, this is another important area we should explicitly account for.

I checked the Maail v3.0 HLD, data-model LLD and agent-runtime LLD.

Memory is already mentioned, but the complete agentic memory architecture shown in your image is not yet designed.

Our current documents already provide:

| Existing capability               | Where it appears                                                            |
| --------------------------------- | --------------------------------------------------------------------------- |
| Conversation history              | `chat_conversations` and `chat_messages`                                    |
| Short-lived derived writing style | `get_style_profile`                                                         |
| Email history                     | Thread and message storage                                                  |
| Agent execution history           | `agent_runs` and `agent_steps`                                              |
| Cached intelligence               | Versioned thread summaries                                                  |
| Semantic memory                   | Not implemented as a dedicated system                                       |
| Procedural memory                 | Partially represented by prompts, manifests and versioned agent definitions |
| Long-term episodic memory         | Not explicitly defined as a separate memory architecture                    |

The README explicitly says persistent memory is deferred in v1 and user writing style is derived on demand. The LLD also stores conversational history in PostgreSQL.&#x20;

README(1).md

02-lld-data-model.md



Let's expand this properly.

# 1. Understand the four types of agentic memory

Your reference diagram identifies four memory categories. We should preserve that distinction.

# Maail Memory System

1\. Episodic Memory

Past experiences and events

What happened? Which conversations, actions and outcomes occurred?

Example: The user previously discussed a Spring Boot authentication issue with a teammate.

2\. Semantic Memory

Facts and learned knowledge

What do we know? What preferences, facts and relationships are useful?

Example: The user's preferred email writing style is concise and professional.

3\. Procedural Memory

Instructions and procedures

How should something be done? What workflows and operating procedures should agents follow?

Example: The approved process for investigating a GitHub pull request.

4\. Working / Conversation Memory

Current session context

What is happening right now? What has the user asked in the current conversation?

Example: The current Companion conversation and selected email thread.

There is an important distinction: episodic, semantic and procedural memory represent different kinds of knowledge. Working memory is temporary operational context. Conversation history is one source of that context, but not all working memory.

# 2. How each memory type should work in Maail

## A. Episodic memory — remembering previous experiences

Imagine a user asks:

"Have I discussed the authentication issue with my teammate before?"

Maail should retrieve the relevant historical events rather than ask the user to explain everything again.

Possible memories:

- Previous email conversations.
- Important project discussions.
- Past internship applications.
- Earlier interview communications.
- Actions previously taken.
- Outcomes of agent workflows.

Recommended storage: PostgreSQL initially.

We already have:

- `email_threads`
- `email_messages`
- `thread_intelligence`
- `thread_summaries`
- `agent_runs`
- `agent_steps`

These provide most of our episodic foundation.

We do not need to copy every email into another memory database.

Later, pgvector can provide semantic recall for experiences that PostgreSQL full-text retrieval cannot find.

## B. Semantic memory — remembering useful facts

Semantic memory should store relatively stable information derived from or explicitly provided by the user.

Examples:

```
User preferences:
- Prefers concise professional replies.

Active interests:
- Machine Learning
- Java
- Backend development

Communication relationships:
- Frequently communicates with a particular project team.

Project knowledge:
- Project X uses Spring Boot.
```

However, I would not permanently save every fact an LLM extracts.

A semantic memory record should have:

- Memory ID.
- User ID.
- Fact or preference.
- Source reference.
- Evidence.
- Confidence or verification status.
- Creation and last-confirmed dates.
- Expiry or invalidation policy.

Recommended storage: PostgreSQL structured records first.

Use embeddings later, if semantic memory retrieval becomes necessary.

Firestore is not required just because it appears in the reference architecture.

## C. Procedural memory — remembering how to perform work

This is particularly interesting for Maail because of our agent-first and MCP-based architecture.

Imagine the Developer Agent has a validated workflow:

```
Investigate technical issue

1. Retrieve the source email.
2. Extract repository and issue identifiers.
3. Verify repository access.
4. Retrieve related GitHub context.
5. Analyze available evidence.
6. Generate a structured finding.
7. Propose an action if appropriate.
```

This is procedural knowledge.

It is not a personal memory. It is an approved operational workflow.

Recommended storage: Git repository.

We can maintain:

```
maail/
├── agent_definitions/
│   ├── triage/
│   ├── developer/
│   ├── summarizer/
│   └── companion/
│
├── procedures/
│   ├── email_investigation.md
│   ├── deadline_handling.md
│   ├── opportunity_analysis.md
│   └── reply_generation.md
│
├── prompts/
├── tool_contracts/
└── evaluation_fixtures/
```

Procedures must be version-controlled, reviewed and tested. Agents should not be allowed to turn arbitrary email instructions into permanent procedures.

Later, GCS or S3 can store large versioned artifacts, such as evaluation bundles or generated documents. Git should remain the source of truth for executable agent procedures and configuration.

## D. Working memory — current conversation and session state

This is the context an agent needs while handling an ongoing interaction.

For example:

User: "Find the email about my API."

Maail retrieves the thread.

User: "Summarize it."

User: "Now draft a reply."

The Companion should retain the selected thread, previous question and current task without retrieving everything again.

Recommended storage:

- PostgreSQL for durable conversation history.
- Application execution context for temporary prompt state.
- Redis only when we have a genuine need for distributed, high-speed session caching.

Our existing `chat_conversations` and `chat_messages` tables already support the durable part.

We should add explicit execution-state handling for multi-step agent workflows rather than treating the entire chat history as working memory.

# 3. Which databases should Maail actually use?

Your diagram uses four storage technologies. Let's evaluate each against our existing architecture.

| Memory type            | Your diagram          | My recommendation for Maail                                |
| ---------------------- | --------------------- | ---------------------------------------------------------- |
| Episodic               | PostgreSQL + pgvector | PostgreSQL first; pgvector later                           |
| Working / conversation | Redis                 | PostgreSQL authoritative; Redis optional cache             |
| Semantic               | Firestore             | PostgreSQL structured memory; embeddings later if required |
| Procedural             | Git / GCS / S3        | Git as source of truth; object storage for large artifacts |

### Why I wouldn't introduce all four immediately

We already have PostgreSQL 16 with RLS, relational storage, full-text search and job management.

Introducing Firestore and Redis immediately creates additional operational responsibilities:

- More authentication and connection management.
- Cross-database consistency.
- More backup and recovery procedures.
- Additional data deletion requirements.
- More complexity in debugging agent behavior.

We should introduce specialized storage only when its capabilities provide measurable value.

## Recommended memory infrastructure

PostgreSQL — Primary memory store

Threads, episodic records, conversation history, structured user facts, summaries, agent execution state.

Git repository — Procedural knowledge

Agent definitions, workflows, instructions, prompts, tool contracts and evaluation fixtures.

Redis — Optional cache

Transient session state, hot memory retrieval and distributed caching when needed.

pgvector — Future semantic retrieval

Similarity search for paraphrased experiences and user knowledge when full-text search is insufficient.

Firestore and separate object storage are not required for the initial implementation.

# 4. Complete Maail Agentic Memory Architecture

I would introduce a central Memory Management Layer between our Agent Runtime and storage systems.

\#chatgpt-mermaid-\_r_43m\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_43m\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_43m\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_43m\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_43m\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_43m\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_43m\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_43m\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_43m\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_43m\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_43m\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_43m\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_43m\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_43m\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_43m\_ p{margin:0;}#chatgpt-mermaid-\_r_43m\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_43m\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_43m\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_43m\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_43m\_ .label text,#chatgpt-mermaid-\_r_43m\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_43m\_ .node rect,#chatgpt-mermaid-\_r_43m\_ .node circle,#chatgpt-mermaid-\_r_43m\_ .node ellipse,#chatgpt-mermaid-\_r_43m\_ .node polygon,#chatgpt-mermaid-\_r_43m\_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-\_r_43m\_ .rough-node .label text,#chatgpt-mermaid-\_r_43m\_ .node .label text,#chatgpt-mermaid-\_r_43m\_ .image-shape .label,#chatgpt-mermaid-\_r_43m\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_43m\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_43m\_ .rough-node .label,#chatgpt-mermaid-\_r_43m\_ .node .label,#chatgpt-mermaid-\_r_43m\_ .image-shape .label,#chatgpt-mermaid-\_r_43m\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_43m\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_43m\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_43m\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_43m\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_43m\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_43m\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_43m\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_43m\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_43m\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_43m\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_43m\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_43m\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_43m\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_43m\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_43m\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_43m\_ .icon-shape,#chatgpt-mermaid-\_r_43m\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_43m\_ .icon-shape p,#chatgpt-mermaid-\_r_43m\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_43m\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_43m\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_43m\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_43m\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_43m\_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_43m\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_43m\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_43m\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_43m\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_43m\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_43m\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_43m\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_43m\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_43m\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_43m\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_43m\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-\_r_43m\_ .node rect,#chatgpt-mermaid-\_r_43m\_ .node circle,#chatgpt-mermaid-\_r_43m\_ .node ellipse,#chatgpt-mermaid-\_r_43m\_ .node polygon,#chatgpt-mermaid-\_r_43m\_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_43m\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_43m\_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_43m\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_43m\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_43m\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}STORAGEMEMORY MANAGEMENT LAYERAGENT RUNTIMEMAAIL AGENT LAYERPostgreSQLRedis - Optionalpgvector - FutureGit RepositoryGCS / S3 - FutureWorking MemoryEpisodic MemorySemantic MemoryProcedural MemoryMemory ConsolidationContext BuilderMemory Retrieval RouterMemory Permission ControllerMemory Write ValidatorTriage AgentDeveloper AgentResponse AgentCompanion AgentOther Specialist Agents

### How memory retrieval works

Suppose the Companion receives:

"Draft a reply to my teammate about the API issue we discussed last week."

The Memory Management Layer can retrieve:

1. Episodic: previous API discussion.
2. Semantic: relevant project and communication preferences.
3. Procedural: approved reply-generation policy.
4. Working: current conversation and selected email.

The Context Builder combines only the relevant information and sends it to the model.

We should not send all four memory stores to every agent on every request.

### Memory access through MCP

Since we are introducing MCP, memory should also be exposed through controlled tools.

For example:

```
Memory MCP Server
│
├── search_episodes
├── get_conversation_history
├── get_user_preferences
├── search_user_knowledge
├── get_procedure
├── propose_memory_update
└── get_agent_execution_state
```

Each agent gets only the tools appropriate to its task and trust plane.

The write operation is especially important: agents can propose memory updates, but deterministic validation must decide whether those updates are permitted.

# 5. Memory lifecycle — how agents should learn and retain information

A memory system shouldn't simply save every piece of information forever.

We need a lifecycle.

\#chatgpt-mermaid-\_r_44j\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_44j\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_44j\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_44j\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_44j\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_44j\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_44j\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_44j\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_44j\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_44j\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_44j\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_44j\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_44j\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_44j\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_44j\_ p{margin:0;}#chatgpt-mermaid-\_r_44j\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_44j\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_44j\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_44j\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_44j\_ .label text,#chatgpt-mermaid-\_r_44j\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_44j\_ .node rect,#chatgpt-mermaid-\_r_44j\_ .node circle,#chatgpt-mermaid-\_r_44j\_ .node ellipse,#chatgpt-mermaid-\_r_44j\_ .node polygon,#chatgpt-mermaid-\_r_44j\_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-\_r_44j\_ .rough-node .label text,#chatgpt-mermaid-\_r_44j\_ .node .label text,#chatgpt-mermaid-\_r_44j\_ .image-shape .label,#chatgpt-mermaid-\_r_44j\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_44j\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_44j\_ .rough-node .label,#chatgpt-mermaid-\_r_44j\_ .node .label,#chatgpt-mermaid-\_r_44j\_ .image-shape .label,#chatgpt-mermaid-\_r_44j\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_44j\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_44j\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_44j\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_44j\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_44j\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_44j\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_44j\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_44j\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_44j\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_44j\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_44j\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_44j\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_44j\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_44j\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_44j\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_44j\_ .icon-shape,#chatgpt-mermaid-\_r_44j\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_44j\_ .icon-shape p,#chatgpt-mermaid-\_r_44j\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_44j\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_44j\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_44j\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_44j\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_44j\_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_44j\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_44j\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_44j\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_44j\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_44j\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_44j\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_44j\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_44j\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-\_r_44j\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_44j\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_44j\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-\_r_44j\_ .node rect,#chatgpt-mermaid-\_r_44j\_ .node circle,#chatgpt-mermaid-\_r_44j\_ .node ellipse,#chatgpt-mermaid-\_r_44j\_ .node polygon,#chatgpt-mermaid-\_r_44j\_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_44j\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_44j\_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_44j\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_44j\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_44j\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}Agent observes informationIdentify memory candidateExtract structured informationValidate source and evidenceIs it useful and permitted?DiscardClassify memory typeCheck duplicate and conflictStore or update memorySet validity and retentionRetrieve when relevantUse in agent contextRefresh, correct or expireNoYes

### Memory management rules

| Operation     | How it should work                                       |
| ------------- | -------------------------------------------------------- |
| Creation      | Only useful, authorized information becomes memory       |
| Deduplication | Don't store the same fact repeatedly                     |
| Updating      | Replace outdated facts while preserving relevant history |
| Retrieval     | Use relevance, source, recency and user scope            |
| Expiration    | Remove stale temporary information                       |
| Correction    | Respect user corrections over inferred facts             |
| Deletion      | Support memory-specific and account-level deletion       |
| Auditing      | Record provenance and memory lifecycle events            |

An important security consideration: an incoming email must never be able to poison Maail's procedural memory by instructing an agent to permanently change its behavior.

# 6. Harness engineering for memory

We should apply harness engineering to memory just as we do to agents.

| Memory component     | Harness mechanism                                  |
| -------------------- | -------------------------------------------------- |
| Working memory       | Context-size limits and automatic summarization    |
| Episodic memory      | Thread linking, deduplication and event provenance |
| Semantic memory      | Fact validation, conflict detection and expiry     |
| Procedural memory    | Git versioning, approval and regression tests      |
| Memory retrieval     | Top-K limits, relevance ranking and scoped access  |
| Memory writes        | Schema validation and write permissions            |
| Memory consolidation | Scheduled deterministic cleanup and deduplication  |
| Memory caching       | Version-aware invalidation                         |
| Memory security      | Tenant isolation and memory-poisoning tests        |
| Memory evaluation    | Recall, relevance, freshness and source accuracy   |

### Five important memory evaluation tests

1. Does Maail retrieve the right previous conversation?
2. Does it avoid retrieving unrelated personal information?
3. Does it recognize that a fact has become outdated?
4. Does it distinguish user-confirmed information from AI inference?
5. Can one user's memory ever appear in another user's results?

These tests should be added to the existing agent evaluation framework.

# 7. What needs updating in the architecture documents?

I would make the following additions.

| Document                     | Required additions                                                                |
| ---------------------------- | --------------------------------------------------------------------------------- |
| `00-gap-analysis.md`         | Memory taxonomy, retention, lifecycle, poisoning and privacy gaps                 |
| `01-hld.md`                  | Dedicated Memory Management Layer in the architecture diagram                     |
| `02-lld-data-model.md`       | Memory records, provenance, versioning, expiry and access policies                |
| `03-lld-agent-runtime.md`    | Memory retrieval tools, write validation, context assembly and memory permissions |
| `04-lld-api-sync-modules.md` | Memory API, worker jobs, cache invalidation and module structure                  |
| `05-harness-engineering.md`  | Memory efficiency, evaluation and lifecycle harnesses                             |
| `README.md`                  | Memory architecture and initial implementation decisions                          |

I would also add a new logical module:

```
modules/
│
├── memory/
│   ├── manager.py
│   ├── router.py
│   ├── retrieval.py
│   ├── consolidation.py
│   ├── lifecycle.py
│   ├── provenance.py
│   │
│   ├── working/
│   ├── episodic/
│   ├── semantic/
│   └── procedural/
│
└── agents/
    └── mcp/
        └── memory_tools/
```

This is a logical module structure. It does not mean each memory type needs its own database or deployment.

# 8. Final architectural decisions I recommend

# Maail Memory Architecture v1

Recommended baseline

| Component        | Decision                                                      |
| ---------------- | ------------------------------------------------------------- |
| Episodic         | Existing PostgreSQL email and intelligence records            |
| Semantic         | Structured PostgreSQL facts, limited and validated            |
| Procedural       | Version-controlled Git knowledge                              |
| Working          | PostgreSQL conversation history + transient execution context |
| Redis            | Deferred                                                      |
| pgvector         | Deferred                                                      |
| Firestore        | Not required                                                  |
| GCS/S3           | Deferred until large artifacts require it                     |
| Memory interface | Memory Management Layer + controlled MCP tools                |
| Memory writes    | Validated, permission-controlled                              |
| Memory retrieval | Demand-driven                                                 |

## 9. The final picture of Maail

At this point, we have four major architectural pillars:

Agent Architecture

Specialized agents, MCP tools and orchestration.

Memory Architecture

Working, episodic, semantic and procedural memory.

Harness Engineering

Efficiency, verification and bounded execution.

Security Architecture

Trust boundaries, RLS, permissions and approvals.

My recommendation: Include memory architecture in HLD v3.1, but don't introduce four different storage technologies just to match the reference diagram.

We should build the memory interfaces and lifecycle now, use the existing PostgreSQL foundation, and add specialized memory infrastructure only when actual retrieval and performance evaluations justify it.

That gives Maail a proper agentic memory design without making the initial application unnecessarily complicated.