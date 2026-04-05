# Spike: Agent Runtime Options

**Date:** 2026-04-05
**Status:** Research complete, decision pending
**Context:** Anthropic's April 3-4 policy enforcement changes how third-party tools can use Claude subscriptions. This document evaluates OpenLoop's options for how agents talk to Claude going forward.

---

## What Changed

On April 3, 2026, Anthropic emailed all subscribers: third-party tools connected to your Claude account now draw from extra usage (pay-as-you-go) instead of your subscription. Enforcement began April 4 at 12pm PT.

The policy is explicit: "OAuth tokens obtained through Claude Free, Pro, or Max accounts cannot be used in any product, tool, or service — **including the Agent SDK**." The Agent SDK is called out by name.

Anthropic's servers distinguish SDK usage from interactive CLI usage via a `cc_entrypoint` header. The Agent SDK sets this to `sdk-py`. Interactive Claude Code sets it to `cli`. Server-side checks can reject subscription OAuth for SDK entrypoints while allowing it for CLI entrypoints.

**What this means for OpenLoop:** OpenLoop uses the Claude Agent SDK with subscription OAuth. Under the new policy, this is explicitly prohibited and subject to hard blocking. We need to evaluate alternatives.

---

## Options at a Glance

| Option | How it talks to Claude | Billing | Policy risk | Engineering effort | Product impact |
|--------|----------------------|---------|-------------|-------------------|----------------|
| **1. Status quo** (Agent SDK + subscription) | SDK spawns CLI with `cc_entrypoint=sdk-py` | Max subscription | **High** — explicitly blocked | None | None |
| **2. Agent SDK + API keys** | Same as today, different auth | Pay-per-use API rates | **None** — officially supported | Minimal | None functionally; cost increases |
| **3. ACP bridge** | ACP protocol → CLI with `cc_entrypoint=cli` | Max subscription | **Low** — same as Zed/JetBrains | High | Moderate losses |
| **4. Direct CLI wrapper** | Subprocess → CLI with `cc_entrypoint=cli` | Max subscription | **Low** — same as ACP | High | Moderate-high losses |
| **5. Terminal Claude Code + OpenLoop as data layer** | You use Claude Code in terminal; OpenLoop is an MCP data source | Max subscription | **None** — this is just using Claude Code | Moderate | Significant product changes |

---

## Option 1: Status Quo (Agent SDK + Subscription OAuth)

### How It Works

OpenLoop calls `claude_agent_sdk.query()`, which spawns the Claude Code CLI binary as a subprocess. The SDK passes your system prompt, MCP tools (hosted in-process), and permission hooks. The CLI talks to Anthropic's API. Tool calls route back to your in-process MCP server. The SDK manages the agentic loop (model call → tool execution → result → continue). You get typed streaming events back.

Authentication is via `CLAUDE_CODE_OAUTH_TOKEN` which bills to your Max subscription.

### Policy Position

Explicitly prohibited. The docs name the Agent SDK by name. Server-side enforcement exists — the `cc_entrypoint=sdk-py` header tells Anthropic's servers this is SDK usage, and subscription OAuth can be rejected for that entrypoint. Account bans have occurred for third-party tool usage detected through activity review.

Thariq Shihipar (Anthropic) said in February 2026 that "nothing is changing about how you can use the Agent SDK and MAX subscriptions" — but this was before the April 3-4 enforcement, the written policy explicitly contradicts it, and there is no formal exemption for personal use.

### Why You Might Stay Here

- Zero engineering effort.
- Everything works today — it may not be actively blocked yet for SDK users.
- If Anthropic clarifies that personal-use SDK development is exempt (GitHub issue #42106 requests this), the problem goes away.

### Why You Might Leave

- You are one enforcement update away from OpenLoop breaking with no warning.
- Account suspension is a real risk — Anthropic has banned accounts for third-party tool usage.
- The policy is unambiguous. Relying on enforcement lag is not a strategy.

### Product Impact

None. Everything works as designed. The risk is that it stops working.

---

## Option 2: Agent SDK + API Key Billing

### How It Works

Identical to today. Same Agent SDK, same code, same architecture. The only change: instead of `CLAUDE_CODE_OAUTH_TOKEN` (subscription billing), you set `ANTHROPIC_API_KEY` (pay-per-use billing). This is one environment variable.

The SDK's official documentation lists API key authentication as the primary supported method. This is the path Anthropic designed for third-party tools.

### Policy Position

Fully compliant. API keys are the officially supported authentication for the Agent SDK. Zero policy risk, zero enforcement risk, zero account risk.

### Why You Might Pick This

- Minimal engineering effort — change one environment variable.
- Zero product impact — everything works exactly as it does today.
- Officially supported by Anthropic. No gray areas.
- You keep all of OpenLoop's capabilities: multi-agent identity, context assembly, background delegation, automations, memory lifecycle, web UI, everything.

### Why You Might Not

- **Cost.** API billing is pay-per-token. A Max subscription is $200/month with generous usage. API billing for equivalent usage could be significantly more — potentially $500-2,000+/month depending on how heavily you use agents. The exact cost depends on your usage patterns.
- You're paying twice if you also keep your Max subscription for interactive Claude Code/Claude.ai use.

### Product Impact

**None.** This is the same product with a different billing path. Every feature, every capability, every workflow works identically. The only change is the bill.

### Cost Consideration

The SDK exposes `total_cost_usd` on every response. OpenLoop could log this and present a daily/weekly/monthly cost dashboard — giving you visibility into what the API path actually costs before you commit. A low-effort spike could answer the cost question definitively.

---

## Option 3: ACP Bridge

### How It Works

ACP (Agent Client Protocol) is an open standard for how editors and clients communicate with AI agents. It's JSON-RPC over stdio — the same protocol Zed and JetBrains use to integrate with Claude Code.

A community project called `claude-code-acp` wraps the Claude Code CLI as an ACP agent. OpenLoop would communicate with this bridge via JSON-RPC, and the bridge spawns the CLI directly. Because it runs the genuine CLI binary, the `cc_entrypoint` is `cli` — the same as interactive terminal use.

OpenLoop's 40+ MCP tools would run as a standalone MCP server process. The CLI connects to this server via its built-in MCP support. The tools themselves don't change — just how they're hosted (external process instead of in-process).

Authentication is via `claude auth login` — your Max subscription, the same way interactive Claude Code authenticates.

### Policy Position

Low risk. This is the same mechanism Zed and JetBrains use, and those are officially supported integrations that work on subscription billing. The `cc_entrypoint` is `cli`, which passes all current enforcement checks.

The remaining risk: automated agent workflows look different from a human coding in an IDE. Anthropic could theoretically detect unusual usage patterns (high frequency, no typing delays, custom MCP tool names). But there's no explicit policy against it, no hard block, and no precedent for enforcement against CLI-based integrations.

### Why You Might Pick This

- Keeps Max subscription billing — no per-token costs.
- Uses the same integration path as officially supported editors.
- Retains most of OpenLoop's architecture and capabilities.
- Structured session management via ACP protocol.

### Why You Might Not

- **Significant engineering effort.** The agent runner needs a major rewrite. MCP tools need to be externalized into a standalone server. Permission hooks need to become CLI shell commands instead of in-process Python.
- **Community dependency.** `claude-code-acp` is not maintained by Anthropic. If it breaks or falls behind CLI updates, you're waiting on the community or forking it.
- **Policy risk isn't zero.** It's low, but "automating Claude Code for agent workflows" is different from "human using an IDE." Anthropic could tighten the definition.

### Product Impact

**What you keep:**
- All MCP tool functionality (same code, external hosting)
- Context assembly (same logic, delivered through ACP session config)
- Memory system (unchanged)
- Agent orchestration (Odin routing, delegation — the conversations just use a different transport)
- Model selection (Haiku/Sonnet/Opus)
- Prompt caching (handled by the CLI binary, same as today)
- Streaming to the frontend (converted to SSE events regardless of source)
- Web UI for data management and monitoring

**What gets worse:**
- **Permission enforcement slows down.** Currently, every tool call runs through an in-process Python hook that checks the database in microseconds. With CLI hooks, every tool call shells out to a Python script that starts up, connects to the database, checks permissions, and returns. This adds roughly 100-500ms per tool call. For a background task making 50 tool calls, that's 5-25 seconds of added total latency.
- **MCP tool hosting adds operational complexity.** Instead of tools running in-process (zero overhead), you manage a separate process. If it crashes, the CLI loses its tools mid-conversation. Needs health checks, restart logic, and graceful shutdown.
- **Background task turn loop needs reimplementation.** The current turn loop (send prompt → check for completion → check steering queue → auto-continue → monitor context → trigger compaction) is ~200 lines of tested code. You'd rewrite this against ACP's session API. Same logic, different plumbing — but it's a source of bugs during transition.
- **Session retry on expiry needs reimplementation.** Currently, if an SDK session expires, the agent runner detects it, reassembles fresh context with conversation summaries, and retries. ~100 lines of code to replicate.

---

## Option 4: Direct CLI Wrapper

### How It Works

OpenLoop spawns the Claude Code CLI directly as a subprocess:

```
claude -p --output-format stream-json --system-prompt "..." --mcp-server "openloop ..." --session-id "..."
```

No SDK. No ACP. You manage the subprocess, parse JSON-lines from stdout, handle sessions via `--session-id` / `--resume` flags. Like ACP, MCP tools run as an external server process. Like ACP, the `cc_entrypoint` is `cli`.

### Policy Position

Same as ACP. Identical mechanism, identical risk profile.

### Why You Might Pick This

- No community dependency — you only depend on the CLI binary, which Anthropic maintains.
- Slightly simpler stack (no ACP protocol layer in between).
- If you want maximum control over the interaction.

### Why You Might Not

- **You'd end up building half of what ACP already provides.** Session lifecycle management, event streaming, error handling — ACP gives you these as a protocol. Without it, you write them yourself.
- **System prompt size limits.** OS-level argument length limits can be ~32KB. Your assembled context can approach that. You'd likely need to write the system prompt to a temporary file and find an alternative delivery mechanism. ACP doesn't have this problem — it sends data over stdio with no size limit.
- **No structured session API.** ACP gives you create/send/receive/close as protocol operations. Direct CLI gives you a subprocess and flags. More fragile, more custom code.

### Product Impact

Same as ACP, plus:
- **System prompt delivery is more fragile** due to argument size limits.
- **More custom code to maintain** for session management, error handling, and streaming.
- **Slightly higher risk of breakage** when CLI output format changes across versions (no protocol contract like ACP provides).

This option exists but ACP is strictly better for the same policy position. The only advantage is avoiding the `claude-code-acp` community dependency.

---

## Option 5: Terminal Claude Code + OpenLoop as Data Layer

### How It Works

The most fundamental shift. You stop using OpenLoop as the agent runtime entirely. Instead:

- You open Claude Code in your terminal — interactive, subscription-covered, no policy concerns.
- Claude Code connects to OpenLoop via MCP — your tools exposed as an MCP server.
- You talk to Claude naturally. It reads and writes to OpenLoop's database through MCP tools.
- OpenLoop's web UI remains for viewing and managing data — spaces, items, boards, documents.
- OpenLoop becomes a **data and state platform**, not an agent orchestration system.

This is unambiguously "ordinary use of Claude Code with MCP servers." It's the intended use case for Max subscriptions.

### Policy Position

No risk whatsoever. This is a person using Claude Code in a terminal with MCP tools. It's what the product is designed for.

### Why You Might Pick This

- **Zero policy risk.** Not low risk, not gray area — zero.
- **Zero ongoing compliance monitoring.** You never have to check whether Anthropic changed enforcement.
- **You get Claude Code's full feature set for free** — subagents, plan mode, extended thinking, `/compact`, `/resume`, session management, agent teams. These are actively developed by Anthropic and improve over time without you doing anything.
- **Moderate engineering effort.** Build the MCP server, write CLAUDE.md instructions, keep the web UI. Less work than ACP or direct CLI rewrites.
- **Simplifies the architecture dramatically.** No agent runner, no session management, no background task orchestration, no concurrency manager. Claude Code handles all of that.

### Why You Might Not

This option trades significant product capabilities for simplicity and compliance. The losses are real.

### Product Impact — What Changes

**Multi-agent identity — lost.**
Currently, each agent has its own system prompt, personality, and domain knowledge. The Recruiting Agent thinks and responds differently from the Engineering Manager. In terminal Claude Code, it's one Claude. You could approximate this with Claude Code skills (SKILL.md files that load on demand), but you lose persistent identity separation between agents. You're always talking to "Claude with access to OpenLoop," not "your Recruiting Agent."

**Automatic context assembly — lost.**
This is the biggest functional loss. Today, every agent conversation automatically includes:
- Top-scored memory facts (importance × recency × access frequency)
- Active behavioral rules (highest confidence first)
- Conversation summaries from prior conversations
- Current board state and working memory

All of this is scored, budgeted to ~8,000 tokens, and ordered for attention optimization (important content at the beginning and end of the prompt).

In terminal Claude Code, none of this happens automatically. You could build a `get_context` MCP tool that returns the same assembled context, and instruct Claude to call it at session start. But it arrives as a tool response (less token-efficient than system prompt placement) and depends on Claude remembering to call it.

**Odin routing — lost.**
No AI front door that decides where to route your request. You decide what to work on and which space to focus on. For a single user who knows their own system, this may not matter much. But the "just type what you need and the system figures it out" experience goes away.

**Background delegation with steering — reduced.**
Claude Code can spawn subagents and work on multi-step tasks. But OpenLoop's structured turn loop — steering queue, progress tracking, step-by-step monitoring on the dashboard, mid-task corrections via the web UI — doesn't exist. You can steer in the terminal, but you lose the dashboard-based monitoring and the structured background task lifecycle.

**Automations — lost.**
No cron-triggered agent runs. Daily task reviews, stale work checks, follow-up reminders — all gone. You'd run these manually or build a separate scheduling mechanism.

**Autonomous long-running sessions — reduced.**
OpenLoop's autonomous mode (give an agent a goal, it works for hours with managed compaction, self-directed task lists, soft budgets) doesn't exist in the same structured way in terminal Claude Code. Claude Code has subagents and can work on complex tasks, but without the managed compaction cycle, budget enforcement, and task list persistence that OpenLoop provides.

**Web-based conversations — lost.**
All conversations happen in the terminal. The web UI still shows your data (spaces, items, boards, documents, memory) but you can't chat with agents through it.

**Conversation continuity — changed.**
Currently, closing a conversation generates a summary. The next conversation with the same agent in the same space gets those summaries injected into context. In terminal Claude Code, you'd use `/resume` to continue sessions or rely on Claude Code's session history and its own auto-memory system. Different mechanism. Works, but less structured.

### Product Impact — What Stays

- All data: spaces, items, documents, memory entries, behavioral rules. Everything in SQLite, accessible via MCP tools.
- The web UI for viewing and managing all data.
- Memory read/write via MCP tools (`save_fact`, `recall_facts`, `save_rule`, etc.).
- Memory lifecycle services (write-time dedup, temporal facts, auto-archival, consolidation) still run as backend processes.
- Board and task management via MCP tools.
- Document access and search.
- Full prompt caching (handled by the CLI).

### A Note on Memory and Learning

OpenLoop's memory system works via MCP tools. These tools can be exposed to terminal Claude Code exactly as they work today. Claude can `save_fact` when it learns something, `recall_facts` to retrieve knowledge, `save_rule` when you correct its behavior. The data is the same, the storage is the same, the lifecycle management is the same.

What changes is delivery. Today, memory is automatically assembled into the system prompt — Claude doesn't have to ask for it, it's just there. In terminal Claude Code, Claude would need to actively query for context. You can mitigate this with CLAUDE.md instructions ("always call `recall_facts` at session start") or by building a `get_workspace_context` tool that returns pre-assembled context for whatever space you're working in.

You could also use Claude Code's built-in auto-memory system (the CLAUDE.md memory files) alongside OpenLoop's memory — Claude Code memory for general preferences and how you like to work, OpenLoop memory for domain-specific knowledge in each space. This hybrid approach may actually work well.

---

## What's Really at Stake

The five options sit on a spectrum between two poles:

**Full product vision (Options 1-3):** Multi-agent identity, automatic context assembly, background orchestration, automations, web-based conversations, structured delegation. This is the OpenLoop described in CAPABILITIES.md — a personal AI command center with agents working for you.

**Simplicity and compliance (Option 5):** Claude Code does the agent work, OpenLoop holds the data. Fewer moving parts, zero policy risk, but a fundamentally different product — more "personal data platform with AI access" than "AI command center."

Options 2, 3, and 4 sit at different points on this spectrum:

- **Option 2 (API keys)** keeps the full product vision but changes the economics. How much the economics change depends on your usage.
- **Option 3 (ACP)** keeps most of the product vision on subscription billing, but with engineering cost and moderate capability losses in the plumbing layer (slower permissions, external process management).
- **Option 4 (Direct CLI)** is similar to Option 3 with slightly more engineering burden and no advantage except removing a community dependency.

---

## Decision Framework

**If cost is not a constraint:** Option 2 (API keys). Zero engineering effort, zero product impact, fully compliant. The only question is whether the monthly bill is acceptable.

**If subscription billing is important and you're willing to invest engineering time:** Option 3 (ACP). Keeps most capabilities, uses the same integration path as officially supported editors, moderate engineering effort.

**If you want the simplest possible setup with zero compliance worry:** Option 5 (Terminal Claude Code). Accept the product tradeoffs — no multi-agent identity, no automations, no web conversations — in exchange for radical simplicity and zero policy risk.

**If you want to defer the decision:** Option 2 as an interim step. Switch to API keys now (one environment variable change), measure actual costs for 2-4 weeks, then decide whether the cost justifies investing in Option 3 or simplifying to Option 5.

---

## Open Questions

1. **What does API billing actually cost for your usage?** The SDK reports `total_cost_usd` on every call. A 2-week measurement period on API keys would give you real data instead of estimates.

2. **Will Anthropic formalize a personal-use exemption for the Agent SDK?** GitHub issue #42106 requests this. If they do, Option 1 becomes viable again. No response from Anthropic as of April 5, 2026.

3. **How critical are automations and background delegation to your workflow?** If you primarily use OpenLoop through direct conversation (not scheduled automations or long-running autonomous goals), Option 5's tradeoffs may be acceptable.

4. **Could a hybrid work?** Option 5 for daily interactive use (terminal Claude Code, subscription billing) plus Option 2 for automations and background delegation (API keys, only for scheduled/autonomous work that runs without you). This limits API costs to the automated work only.

---

## Sources

- [Boris Cherny announcement (April 3, 2026)](https://www.threads.com/@boris_cherny/post/DWsAWeND5nm/)
- [TechCrunch coverage (April 4)](https://techcrunch.com/2026/04/04/anthropic-says-claude-code-subscribers-will-need-to-pay-extra-for-openclaw-support/)
- [VentureBeat coverage (April 4)](https://venturebeat.com/technology/anthropic-cuts-off-the-ability-to-use-claude-subscriptions-with-openclaw-and)
- [Claude Code Legal and Compliance](https://code.claude.com/docs/en/legal-and-compliance)
- [Agent SDK Overview (policy note)](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Agent SDK Cost Tracking](https://platform.claude.com/docs/en/agent-sdk/cost-tracking)
- [GitHub Issue #42106 — Personal-use SDK request](https://github.com/anthropics/claude-code/issues/42106)
- [GitHub Issue #559 — SDK Max plan billing](https://github.com/anthropics/claude-agent-sdk-python/issues/559)
- [Thariq Shihipar on X — "Nothing is changing"](https://x.com/trq212/status/2024212378402095389)
- [claude-code-acp (CLI bridge)](https://github.com/harukitosa/claude-code-acp)
- [claude-agent-acp (SDK bridge)](https://github.com/agentclientprotocol/claude-agent-acp)
- [ACP MCP integration (DeepWiki)](https://deepwiki.com/zed-industries/claude-code-acp/7.2-model-context-protocol-(mcp))
- [The Natural 20 — OAuth Lockdown](https://natural20.com/coverage/anthropic-banned-openclaw-oauth-claude-code-third-party)
- [Groundy — What It Means for Developers](https://groundy.com/articles/anthropic-bans-third-party-use-subscription-auth-what-it/)
- [Claude Code Costs Documentation](https://code.claude.com/docs/en/costs)
- [Using Claude Code with Pro/Max Plans](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)
