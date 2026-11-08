# Maail LLD — UI Specification (locked)

Transcribed from `gptArc.md` §§3–7, 11, and the Feature Controls section. **Nothing here is
changed.** The design system, palette, typography, layout, navigation, all eleven screens and
the full feature-toggle list are as originally specified.

Where the architecture adds a component, it is because the original spec already *asked* for
the behaviour — §10 lists each one and quotes the line that requires it. No new design
decisions have been introduced.

## 1. Locked product direction

| Dimension | Locked value |
|---|---|
| Target audience | Developers first |
| Theme | Adaptive light + dark |
| Experience | Email + AI workspace (hybrid) |
| Product category | AI communication intelligence |
| Tagline | *Your inbox deserves a brain.* |

Design intent, verbatim: *light theme as the default · warm off-white backgrounds · deep
charcoal typography · soft violet as the primary accent · rounded cards with subtle borders ·
generous whitespace · small, meaningful animations · minimal icons and typography-led design.*

> "The interface should feel like a combination of a premium email client and an intelligent
> developer workspace."

## 2. Colour palette

| Hex | Name | Role |
|---|---|---|
| `#F7F6F3` | Warm white | Light background |
| `#FFFFFF` | Pure white | Cards and panels |
| `#8B70D6` | Maail violet | Primary actions |
| `#25232B` | Charcoal | Dark theme surfaces |
| `#E8E2F5` | Soft lavender | AI highlights |
| `#DDEBE2` | Soft green | Success states |

Soft lavender is the AI-highlight colour, which makes it the visual carrier of the
AI-versus-fact distinction in §10.1.

## 3. Typography

| Usage | Font |
|---|---|
| Brand and major headings | Plus Jakarta Sans |
| Body text | Inter |
| Technical information | JetBrains Mono |
| Email content | Inter |

## 4. Component style

- Border radius: **10–14px**
- **Subtle borders instead of heavy shadows**
- Compact but readable email rows
- Consistent **8px spacing scale**
- **Lucide** icons
- Smooth **150–200ms** interactions
- **Skeleton loaders** for email synchronization
- Clear **empty, error and offline** states

## 5. Dark theme

> "Dark mode should be a carefully designed alternative, not simply inverted light mode."

System preference supported, alongside manual light/dark selection. Charcoal `#25232B` is the
dark surface base.

## 6. Layout — three regions

| Region | Contains |
|---|---|
| Left sidebar | Navigation and workspaces |
| Centre | Current page or email content |
| Right panel | Contextual AI intelligence |

> "The AI panel should follow the user throughout the application and adapt its context to the
> currently selected email, conversation or task."

### AI panel — option C, locked

> "A compact floating AI entry point, expandable into a contextual side panel, with a
> full-screen companion available for complex conversations."

Three states: **collapsed affordance → contextual panel → full-screen companion.** One store
holds panel state across pages; it is not per-page.

## 7. Global navigation

| Item | Purpose |
|---|---|
| Overview | Personal command center |
| Inbox | Complete email workspace |
| Priority | Important messages |
| Developer Hub | Technical email intelligence |
| AI Companion | Conversational assistant |
| Agents | Specialized AI agents |
| Tasks & Deadlines | Extracted action items |
| Insights | Communication intelligence |
| Settings | Personalization and integrations |

Sidebar grouping as originally sketched: **Workspace** (Overview, Inbox, Priority),
**Categories** (Opportunities, Development, Academics, Announcements, Promotions),
**Intelligence** (AI Companion, Developer Hub, Agents, Tasks, Insights).

## 8. Responsive

| Feature | Desktop | Mobile |
|---|---|---|
| Inbox | Three-pane | Single-pane |
| AI companion | Persistent side panel | Separate view |
| Developer Hub | Full dashboard | Stacked cards |
| Agents | Detailed workspace | Agent list |
| Tasks | List and calendar | List-first |
| Settings | Sidebar | Navigation list |

> "On smaller screens, we should never squeeze the three desktop panels into one narrow view."

## 9. The eleven screens

Release priorities exactly as specified.

| # | Screen | Priority | Phase |
|---|---|---|---|
| 01 | Welcome & onboarding | **P0** | 1 |
| 02 | Account connection | **P0** | 1 |
| 03 | Overview dashboard | **P0** | 7 |
| 04 | Smart Inbox | **P0** | 2 → 6 |
| 05 | Email Detail & Intelligence | **P0** | 3 → 8 |
| 06 | AI Companion | **P0** | 10 |
| 07 | Developer Hub | P1 | 13 |
| 08 | Agent Workspace | P1 | 14 |
| 09 | Tasks & Deadlines | P1 | 9 |
| 10 | Insights & Memory | P2 | 15 |
| 11 | Settings & Integrations | **P0** | 11 |

### Screen 01 — Welcome & onboarding

```
maail.                                      Sign in

              Your inbox deserves
                  a brain.

       Understand more. Manage less.

       Your personal AI companion for
       smarter email and development work.

             [ Get started → ]

        Privacy-first · You stay in control

              [ Product preview ]
```

Interactions: Get started → registration · Sign in → existing account · Product preview →
interactive demonstration · Privacy → explains email permissions and data handling.

### Screen 02 — Account connection

```
maail.                         Step 1 of 3

       Let's connect your inbox.

       Maail needs access to your email
       to understand your communication.

       ┌─────────────────────────────┐
       │       Google Gmail          │
       │     Connect account →       │
       └─────────────────────────────┘

       What Maail can do:
       ✓ Read and organize emails
       ✓ Generate summaries
       ✓ Prepare response drafts

       Permissions and privacy →
```

Requirements: Google OAuth 2.0 · least-privilege permissions · clear explanation of every
requested scope · **separate authorization for sending emails** · disconnect account option ·
**connection and synchronization status**.

### Screen 03 — Overview / Command Center

```
Good morning, [name]              │ Maail AI
Your day, simplified.             │ Daily briefing
                                  │
┌────────┐ ┌───────────┐          │ You have 3
│  24    │ │     5     │          │ important
│ Emails │ │ Attention │          │ emails today.
└────────┘ └───────────┘          │
                                  │ 2 opportunities
Today's important items           │ 1 deadline
                                  │ 1 technical issue
[GitHub] CI failure               │
[Recruiter] Interview             │ [ Explore → ]
[Team] API discussion             │
                                  │ Ask Maail...
Upcoming deadlines                │
```

| Component | Behaviour |
|---|---|
| Greeting | Time-aware greeting |
| Email summary | New, unread and processed counts |
| Priority cards | Messages requiring attention |
| Daily briefing | AI-generated digest |
| Upcoming deadlines | Extracted dates |
| Developer activity | Technical messages and issues |
| AI panel | Contextual questions and actions |

Interaction: clicking a GitHub failure card goes **directly to the email detail screen with
Developer Intelligence activated in the right panel.**

> "counts and AI-generated classifications must be clearly separated. We shouldn't present
> estimated urgency as a factual status."

### Screen 04 — Smart Inbox

```
Inbox                      │ Email preview
Search emails...           │ Select an email
                           │
[All] [Unread]             │ Subject
[Important] [Tech]         │
                           │ Sender details
GitHub                     │
CI pipeline failed         │ Message body
10:30 AM                   │
                           │
Recruiter                  │
Interview invite           │
09:15 AM                   │
```

Filters: **All emails · Unread · Important · Technical · Opportunities · Team communication ·
Notifications · Archived**

Every email row displays: sender avatar and name · subject · short preview · received
timestamp · **AI category** · **priority indicator** · attachment indicator when applicable.

AI classification badges: `High priority` · `Technical` · `AI classified`.

> "The user should be able to correct an incorrect classification. These corrections can
> improve future personalization."

### Screen 05 — Email Detail & Intelligence

```
Email                        │ Maail Intelligence
Subject: CI pipeline failed  │ ✧ AI Summary
From: GitHub Actions         │ Build failed because
Date: 10:30 AM               │ tests did not pass.
                             │
Message body                 │ ✧ Important details
Build #284                   │ Branch: development
Test suite failed.           │ Status: Failed
3 tests unsuccessful.        │
                             │ ✧ Suggested actions
[Reply] [Forward]            │ [Investigate]
[Archive]                    │ [Draft response]
                             │ [Find related emails]
```

Intelligence panel sections, in order:

1. **Summary** — what is this email about?
2. **Intent detection** — what does the sender expect from the user?
3. **Extracted entities** — project names · repository names · technologies · dates · error
   messages · people and organizations
4. **Action items** — what needs to happen next?
5. **Related context** — other emails, previous discussions, connected resources
6. **Suggested response** — a draft based on the message and conversation history

> "The user should always be able to distinguish: Information explicitly present in the
> email. AI-generated interpretations. Information retrieved from external integrations."

### Screen 06 — AI Companion

```
Conversations │ Maail Companion
New chat      │ What would you like to
              │ understand today?
Recent chats  │
Internship    │ ┌─────────────────────────┐
preparation   │ │ Find my pending         │
API debugging │ │ internship replies.     │
CI failure    │ └─────────────────────────┘
              │ Maail: I found 4 relevant
              │ conversations.
              │ [Conversation results]
              │
              │ Ask anything about emails...
              │                        [↑]
```

Example prompts, as specified: *Find pending internship emails · What did my teammate say
about the API? · Summarize my technical conversations · Draft a response to the recruiter ·
Which emails need my attention?*

UX requirements: conversation history · source email references · **clickable references to
original emails** · follow-up questions · suggested prompts · regenerate and edit response ·
**explicit confirmation before sending or modifying emails**.

### Screen 07 — Developer Hub

```
Developer Hub
Technical communication, organized.

┌──────────────┐ ┌──────────────┐ ┌────────────────┐
│ 3            │ │ 2            │ │ 1              │
│ CI failures  │ │ API issues   │ │ Pending review │
└──────────────┘ └──────────────┘ └────────────────┘

Technical activity
┌────────────────────────────────────────────────────┐
│ GitHub: Build failure                              │
│ Test failure in payment-service                    │
│ [Analyze issue]                                    │
├────────────────────────────────────────────────────┤
│ Team: API integration                              │
│ Authentication endpoint discussion                 │
│ [View discussion]                                  │
└────────────────────────────────────────────────────┘

Connected tools: GitHub · More integrations
```

> "Maail should not claim to have diagnosed or fixed a bug merely because an email mentions
> an error. It should gather evidence and prepare useful debugging context."

### Screen 08 — Agent Workspace

Agent cards with name, description and `Active` status: **Developer Agent** (understands
technical emails, errors and development discussions) · **Opportunity Agent** (finds
internships, jobs, events and professional opportunities) · **Deadline Agent** (extracts
dates, reminders and action items) · **Response Agent** (prepares personalized email drafts) ·
**Inbox Organization Agent** (classifies and organizes messages).

Agent detail view: purpose · inputs and permissions · recent executions · actions performed ·
reasoning summary and evidence · errors and execution status · user approval requirements ·
enable/disable controls.

> "We should show understandable execution explanations rather than exposing raw internal
> chain-of-thought."

### Screen 09 — Tasks & Deadlines

```
Tasks & Deadlines
Your pending actions

[All] [Today] [Upcoming] [Completed]

TODAY
□ Reply to internship recruiter
  From: Recruitment Team · Due: Today

UPCOMING
□ Prepare for technical interview
  From: Interview confirmation · Due: 10 November
□ Review API integration discussion
  From: Development Team · Due: 12 November

COMPLETED
✓ Reply to project coordinator
```

Interactions: create task from an email · mark complete · change deadline · **link back to
source email** · add notes · set reminders · **correct AI-extracted dates**.

> "We must distinguish an actual sender-specified deadline from a date Maail inferred."

### Screen 10 — Insights & Personal Memory

**Communication analytics** — incoming emails over time · important versus low-priority ·
pending replies · most active conversations.

**Developer analytics** — technical issue discussions · common project references · repeated
error patterns · open development conversations.

**Personal memory** — writing style · frequently discussed topics · active projects ·
frequently contacted people.

> "Users must be able to inspect, edit and delete these stored preferences and memories."

### Screen 11 — Settings & Integrations

| Section | Controls |
|---|---|
| Account | Profile, authentication |
| Email accounts | Gmail connection, synchronization |
| AI preferences | Model, response style |
| Memory | Inspect and manage personal context |
| Agents | Enable/disable and permissions |
| Integrations | GitHub, Calendar |
| Privacy | Data access, retention, deletion |
| Appearance | Light, dark, system |
| Notifications | Priority and deadline alerts |

## 10. Feature Controls — the full locked list

Header: **Personalize your intelligence** — *"Choose what Maail should handle for you. You can
change these anytime."*

Footer: `N features enabled` · `Enable all` · `Save configuration`

### Email intelligence

| Toggle | Description | Default |
|---|---|---|
| Priority detection | Identify urgent, important and time-sensitive emails. | **on** |
| Smart categorization | Automatically classify emails into meaningful categories. | **on** |
| Instant summaries | Generate concise summaries of lengthy emails. | **on** |
| Action extraction | Find tasks, commitments and requested actions in conversations. | **on** |
| Conversation tracking | Connect related emails into a single conversation context. | **on** |

### Developer intelligence

| Toggle | Description | Default |
|---|---|---|
| Technical email detection | Identify API issues, CI failures, bugs and development discussions. | **on** |
| Error context extraction | Extract stack traces, error messages, technologies and affected services. | **on** |
| GitHub context linking | Connect relevant emails with GitHub issues, pull requests and repositories. | off |
| Technical discussion memory | Keep track of ongoing technical discussions and their context. | off |

### Productivity

| Toggle | Description | Default |
|---|---|---|
| Deadline detection | Identify deadlines and important dates from emails. | **on** |
| Follow-up reminders | Detect conversations waiting for your response. | **on** |
| Opportunity discovery | Identify internships, jobs, hackathons and relevant opportunities. | off |
| Daily intelligence briefing | Prepare a personalized summary of what matters each day. | off |

### Writing & communication

| Toggle | Description | Default |
|---|---|---|
| Personalized reply drafts | Generate replies matching your preferred writing style. | **on** |
| Tone adjustment | Rewrite messages to sound professional, friendly or concise. | off |
| Email quality checker | Check clarity, grammar and missing information before sending. | off |
| Meeting preparation | Prepare context from emails before an upcoming meeting. | off |

Ten enabled by default, as specified.

### Per-feature configuration

| Feature | Additional configuration |
|---|---|
| Priority detection | Urgency sensitivity |
| Smart categorization | Custom categories |
| Instant summaries | Short / detailed |
| Deadline detection | Reminder preferences |
| Opportunity discovery | Preferred roles and technologies |
| Personalized replies | Formality and writing style |
| Follow-up reminders | Number of days before reminder |
| Technical detection | Technologies and projects of interest |

Priority detection drawer, verbatim: **Strict** — only genuinely urgent emails · **Balanced** —
important and time-sensitive emails · **Sensitive** — include potentially important emails.

### Presets

| Preset | Label | Contents |
|---|---|---|
| **Minimal** | Lightweight | Priority detection · Email summaries · Smart categorization |
| **Productivity** | Recommended | Everything in Minimal + Action extraction · Deadline detection · Follow-up reminders · Personalized reply drafts |
| **Developer** | Developer-first | Everything in Productivity + Technical email detection · Error context extraction · GitHub context linking · Technical discussion memory |

### Three entry points

- **A — during onboarding**, after connecting Gmail, with recommended presets
- **B — Settings → AI preferences**, the complete control center
- **C — contextual suggestions**, e.g. *"Want Maail to automatically identify upcoming deadlines?"*

## 11. Components the architecture adds — and the line that requires each

Nothing below is a new design decision. Each one implements a behaviour the original spec
already asked for; the architecture only names the component that satisfies it.

| Component | Required by this line in the original spec |
|---|---|
| `AiValue` — one component for every AI-derived value, carrying a source affordance that opens the evidence span | *"The user should always be able to distinguish: Information explicitly present in the email. AI-generated interpretations. Information retrieved from external integrations."* (Screen 05) |
| Per-capability status chips (`analysing` / `ready` / `failed`) | *"Skeleton loaders for email synchronization"* + *"Clear empty, error and offline states"* (§4) |
| Classification override control on email rows | *"The user should be able to correct an incorrect classification."* (Screen 04) |
| Approval card showing the action and its target before execution | *"Explicit confirmation before sending or modifying emails."* (Screen 06) |
| Sync progress indicator and `reauth_required` banner | *"Connection and synchronization status"* (Screen 02) |
| Deadline ambiguity resolver — asks rather than guessing | *"We must distinguish an actual sender-specified deadline from a date Maail inferred."* (Screen 09) |
| Separate send authorization, distinct from read access | *"Separate authorization for sending emails."* (Screen 02) |
| Evidence-gated finding display in Developer Hub | *"Maail should not claim to have diagnosed or fixed a bug merely because an email mentions an error."* (Screen 07) |
| Memory inspector with per-fact source and delete | *"Users must be able to inspect, edit and delete these stored preferences and memories."* (Screen 10) |
| Readable execution summaries in Agent Workspace | *"understandable execution explanations rather than exposing raw internal chain-of-thought"* (Screen 08) |

## 12. Public website — separate build track

Seven sections, as specified: **Hero** (*Your inbox deserves a brain.*) · **The problem**
(too many emails, too little context) · **How Maail works** (understand, organize, act) ·
**AI agents** (specialized intelligence) · **Developer intelligence** (technical communication
workflows) · **Privacy and security** (transparent access and user control) · **Call to
action** (get started with Maail).

Built after v1 ships, from the same design tokens. It is not on the application critical path.
