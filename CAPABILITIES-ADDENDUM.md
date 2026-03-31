# OpenLoop: Agent Intelligence Upgrade

**Status:** Draft for review
**Date:** 2026-03-31
**Context:** Based on analysis of OpenClaw, NanoClaw, Nanobot, PicoClaw, and 20+ comparable tools; validated against academic research on agent memory, context management, and behavioral learning (MemGPT/Letta, Mem0, Zep, CrewAI, LangMem, ReMe, Voyager, plus Anthropic and OpenAI published guidance).
**Audience:** Product decision-maker. Focuses on what the user experiences and why it matters.

---

## Executive Summary

OpenLoop's agents currently have a solid foundation: three-tier memory (facts, conversation summaries, board state), context assembly with token budgets, and persistent conversations via the Claude SDK. This gets you to "agents that remember some things."

The gap is between "remembers some things" and "gets smarter over time." The research converges on a clear finding: **the field has settled on four memory types, not three, and the missing one — procedural memory (learned behaviors) — is the tier that makes agents feel like they're improving.** Beyond that, how agents write, retrieve, and protect memory is as important as what they store.

This document proposes upgrades in four areas, grounded in what's proven to work across production systems and academic research. Each item describes what the user experiences, not just what the system does.

---

## A. Memory Architecture Upgrade

OpenLoop's current memory maps to three of the four established cognitive memory types:

| Memory Type | What It Stores | OpenLoop Today | Status |
|---|---|---|---|
| **Working Memory** | What's happening right now | Board state + recent conversation turns | Covered |
| **Semantic Memory** | Facts and knowledge | `memory_entries` table | Covered |
| **Episodic Memory** | What happened before | `conversation_summaries` table | Covered |
| **Procedural Memory** | How to behave, what the user prefers | *Nothing* | **Missing** |

The four-type model appears independently across Letta/MemGPT, LangMem, CrewAI, and the "Memory in the Age of AI Agents" survey (Dec 2025). No production system found uses fewer than three types. The evidence from LangMem, ReMe, and CrewAI strongly shows that procedural memory is the tier that drives behavioral improvement over time.

---

### A1. Procedural Memory — Agent Learning from Corrections

**What the user experiences today:**

You tell your Recruiting Agent "don't send follow-up emails without checking the CRM first." The agent follows this instruction for the rest of the conversation. Next week, you open a new conversation with the same agent. It sends a follow-up email without checking the CRM. You correct it again. This cycle repeats every few sessions because the correction lives in a conversation summary — a paragraph buried among many other details — not as a first-class behavioral rule.

**What the user experiences after this change:**

When you correct an agent, that correction is captured as a persistent behavioral rule: "Always check CRM before drafting follow-up emails." This rule is injected into the agent's context at the start of every future conversation, with high priority. The agent doesn't repeat the same mistake. Over weeks of use, the agent accumulates a profile of how you want it to work — your preferences, your standards, your workflow patterns. It feels like the agent is learning.

**How it works (simplified):**

A new memory category — behavioral rules — sits alongside facts and summaries. When the system detects a correction in conversation (or the user explicitly says "remember this for next time"), the rule is extracted, generalized ("don't do X in this specific case" becomes "before doing X, always check Y"), and stored with a confidence score. During context assembly, the top-ranked behavioral rules are injected into the system prompt section — the highest-priority position in the context window. Rules that are confirmed by the user gain confidence; rules that are overridden lose it.

**Why it's important:**

This is the difference between a tool and an assistant. A tool does the same thing every time. An assistant adapts to how you work. Every comparable system that users describe as "feeling smart" has some form of this: CrewAI's training system, LangMem's procedural memory, Claude Code's own CLAUDE.md feedback memories. OpenLoop agents should have it too.

**Evidence:** LangMem demonstrated that prompt-evolution from correction feedback produces measurably better agent behavior. ReMe showed that a smaller model (Qwen3-8B) with good procedural memory outperformed a memoryless larger model (Qwen3-14B) — memory quality substitutes for model scale.

---

### A2. Temporal Fact Management — Facts That Know When They Were True

**What the user experiences today:**

In your Recruiting space, you note that "Alice owns the hiring budget." Two months later, Bob takes over. You tell the agent "Bob now owns the hiring budget." The agent writes a new memory entry. But now you have two facts: "Alice owns the hiring budget" (from January) and "Bob owns the hiring budget" (from March). If the context assembler pulls in both, the agent gets confused. If it only pulls in the newer one, you lose the history — and can't answer "who owned the budget in January?" If the agent happens to use a different key name for the new fact, both persist indefinitely without any indication they're related.

**What the user experiences after this change:**

When you say "Bob now owns the hiring budget," the system recognizes this supersedes the Alice fact. The old fact gets marked as "valid until March 2026." The new fact gets "valid from March 2026." The agent's context shows only the current fact (Bob), but if you ask "who handled the budget before Bob?" the agent can look up the historical record. Facts don't pile up in contradiction — they form a clean timeline.

For CRM use cases this is especially powerful: "When did we last change our point of contact at Company X?" "What was our pricing strategy before the Q2 pivot?" These questions become answerable because the system preserves what changed and when, not just the latest state.

**How it works (simplified):**

Two new fields on memory entries: `valid_from` (defaults to creation time) and `valid_until` (defaults to null, meaning "still true"). When a new fact is saved, the system compares it against existing facts in the same namespace. If it contradicts an existing fact, the old fact's `valid_until` is set to now, and the new fact is created with `valid_from` set to now. The agent never sets `valid_until` by guessing — it's either triggered by a contradicting new fact or set explicitly ("Alice is budget owner until end of Q1").

During context assembly, only facts where `valid_until IS NULL` (currently true) are injected. Historical facts are available via the `recall_facts` tool with a date filter.

**Why it's important:**

Without this, memory either contradicts itself (both facts present) or loses history (old fact deleted). Neither is acceptable for a system that's supposed to be your institutional memory. Zep built their entire product around this concept and demonstrated 18.5% accuracy improvement in cross-session retrieval.

---

### A3. Write-Time Fact Management — Dedup at the Source

**What the user experiences today:**

Over several conversations, the agent accumulates variations of the same fact: "Project uses React 19," "Frontend is React 19 with Vite," "Using React 19 + Tailwind v4." Each is stored as a separate memory entry because they have different keys or slightly different wording. When context is assembled, these near-duplicates waste token budget — three entries saying roughly the same thing — while other more unique facts get crowded out.

**What the user experiences after this change:**

Memory stays lean. When the agent learns "Using React 19 + Tailwind v4," the system recognizes this subsumes the earlier "Project uses React 19" entry and updates it rather than adding a new one. The user never sees duplicate or near-duplicate facts. The token budget is spent on diverse, useful information rather than redundant entries.

**How it works (simplified):**

Every memory write triggers a comparison against existing facts in the same namespace. The system (using the LLM for judgment, since semantic matching with keyword search alone is insufficient) decides one of four operations:

- **ADD** — genuinely new fact, no existing entry covers this
- **UPDATE** — existing fact should be modified to incorporate new information
- **DELETE** — existing fact is now obsolete (triggers `valid_until` from A2)
- **NOOP** — this information is already captured, skip

This happens at write time, not as a periodic cleanup job. Bloat is prevented at the source. Mem0 demonstrated 26% improvement in memory quality and 91% lower retrieval latency with this approach versus append-only storage.

**Why it's important:**

Memory bloat is the #1 documented failure mode across agent systems. Without write-time management, the system either wastes context budget on duplicates or requires manual curation. Neither scales. Every production memory system that works at scale (Mem0, CrewAI, Zep) does dedup on write, not after.

---

### A4. Smarter Retrieval — The Right Facts, Not Just the Recent Ones

**What the user experiences today:**

You've been using your Project space for 3 months. The agent has 80+ facts stored. When you start a new conversation, the context assembler loads the most recent facts that fit in the token budget. But the most recent facts might be trivial ("standup moved to 10am") while important foundational facts ("the API uses JWT tokens," "deploy target is AWS us-east-1") haven't been accessed recently and drop off. The agent in conversation 30 doesn't know things the agent in conversation 2 knew.

**What the user experiences after this change:**

The agent consistently remembers the important things — not just the recent things. Frequently-referenced facts stay in context regardless of when they were written. A fact about the project's architecture that gets pulled into every conversation ranks higher than yesterday's meeting note. Facts that haven't been accessed in months naturally fade, but high-importance facts resist fading.

**How it works (simplified):**

Instead of sorting facts by `updated_at`, the context assembler scores each fact:

```
score = importance x decay_factor x (1 + access_boost)
```

Where:
- `importance` — set by the agent when writing the fact (0.0 to 1.0), with higher-importance facts decaying more slowly
- `decay_factor` — based on days since last access, using an Ebbinghaus-inspired curve (important facts decay slowly; trivial facts decay fast)
- `access_boost` — increases with each retrieval, so frequently-used facts stay prominent

Three new fields on memory entries: `importance` (float), `access_count` (integer), `last_accessed` (timestamp). Updated automatically during context assembly.

**Why it's important:**

Simple recency ordering breaks down after ~2 months of active use. The system has more facts than fit in the token budget, and the sorting determines agent quality. This scoring formula is converged-upon across CrewAI (composite scoring), Zep (temporal decay), and independent research (YourMemory's Ebbinghaus implementation showed 34% recall vs. 18% for Mem0's simpler approach on the LoCoMo benchmark).

---

### A5. Agent-Managed Memory Tools

**What the user experiences today:**

Agents have `read_memory` and `write_memory` tools but use them passively — writing a fact when explicitly told to, reading when the system injects context. The agent doesn't proactively manage what it knows. It doesn't merge related facts, delete stale ones, or decide that something discussed in conversation is worth saving for later.

**What the user experiences after this change:**

Agents actively curate their knowledge. During a conversation about restructuring the API, the agent notices this is an important architectural decision and saves it as a fact without being asked. When the agent writes "API will use REST, not GraphQL," it checks existing memory and updates the old entry that said "evaluating GraphQL vs REST" rather than adding a duplicate. The user can see what the agent has saved (memory is browsable in the UI) but doesn't have to manage it themselves.

This also means agents can be explicitly instructed to organize their knowledge: "Review your memory for this space and clean up anything outdated." The agent has the tools to actually do this.

**How it works (simplified):**

Enhanced MCP tools replace the current `read_memory`/`write_memory`:

- `save_fact(content, importance, category)` — saves with write-time dedup (A3)
- `update_fact(fact_id, new_content)` — explicitly updates an existing fact
- `recall_facts(query, date_range?, category?)` — searches with scoring (A4)
- `delete_fact(fact_id, reason)` — marks as superseded with audit trail

Agent system prompts include instructions to use these tools proactively: save important decisions, update outdated information, and flag contradictions. The pre-compaction flush pipeline (B1) triggers these tools automatically before any context compression.

**Why it's important:**

The Letta/MemGPT paper established that agent-managed memory outperforms application-managed memory because the LLM can reason about relevance in context. The application provides infrastructure; the LLM provides judgment about what matters. Nanobot's implementation confirmed this: letting the model decide what to save via structured tools produced better memory quality than mechanical extraction.

---

### A6. Context Ordering — Exploit How Models Pay Attention

**What the user experiences today:**

No visible change — this is invisible infrastructure. But it affects how often agents "miss" information that's in their context.

**What the user experiences after this change:**

Agents more reliably act on important context. Fewer instances of the agent ignoring a fact that was in its context window. Fewer "I already told you this" moments.

**How it works (simplified):**

Models attend strongly to the beginning and end of their context window, and poorly to the middle (the "Lost in the Middle" finding, confirmed architecturally by MIT/Google). Current context assembly stacks tiers in a fixed order. After this change:

- **Beginning of context:** System prompt, procedural memory (behavioral rules), tool documentation — the things that should always be followed
- **Middle of context:** Semantic memory (facts), episodic memory (conversation summaries) — reference material
- **End of context (closest to the user's message):** Working memory (board state, current task context), recent conversation turns — the most immediately relevant information

This is a reordering of existing content, not new content. The evidence is strong: GPT-4 accuracy varies from 98.1% to 64.1% based on where information is placed in context, with identical content.

**Why it's important:**

Free improvement. Same information, better results, zero additional cost. Every token spent is already being spent — this just arranges them for maximum impact.

---

### A7. Memory Lifecycle Management — Preventing Bloat at 6 Months

**What the user experiences today:**

Nothing yet — the system is new. But here's what happens without lifecycle management:

After 6 months of active use across 5 spaces, you have ~500-800 facts, ~390 conversation summaries, and a growing pile of superseded temporal facts (from A2) that were marked as "no longer true" but never cleaned up. The write-time dedup (A3) has been catching duplicates, but the database still grows. The LLM comparison step in dedup gets slower because it's comparing each new fact against hundreds of existing entries. Context assembly still works (it only loads the top-scored entries), but the memory browsing UI in settings shows a wall of entries — many stale, some contradictory, hard to curate manually.

**What the user experiences after this change:**

Memory manages itself. Each space has a fact cap (50 entries). When the cap is reached, the lowest-scored entries (using A4's scoring formula) are archived — moved out of active retrieval but still searchable if an agent explicitly looks for them. Superseded temporal facts (those with `valid_until` set more than 90 days ago) are automatically archived. Procedural rules that haven't been applied in 10+ sessions or that have low confidence are demoted to "inactive" — still in the database, but no longer injected into the agent's context.

Once a month (or on manual trigger from space settings), the system runs a "memory health check": the LLM reviews active facts for a space, merges related entries (e.g., three separate facts about the tech stack become one comprehensive entry), flags contradictions, and suggests deletions. The results are surfaced to the user as a notification: "Memory review for Project space: merged 4 entries, found 2 contradictions, suggest removing 3 stale entries. [Review]." The user approves, adjusts, or dismisses.

**How it works (simplified):**

**Hard caps with eviction:**
- 50 active facts per space namespace
- 20 active facts per agent namespace
- 30 active procedural rules per agent
- When a cap is hit during a write, the lowest-scored entry (by A4 scoring) is archived before the new entry is added
- Archived entries get `archived_at` timestamp, excluded from context assembly, still searchable via tools

**Automatic archival:**
- Superseded temporal facts (`valid_until` set > 90 days ago) are auto-archived on a weekly check
- Procedural rules not applied in 10+ sessions and with confidence < 0.3 are auto-demoted to inactive

**Periodic consolidation (monthly or manual):**
- LLM reviews all active facts for a space
- Merges related entries (3 facts about the tech stack → 1 comprehensive fact)
- Identifies contradictions and surfaces them to the user
- Suggests archival for facts with zero access in 60+ days
- Results shown as a notification requiring user action — the system doesn't delete or merge without approval

**Dedup comparison optimization:**
- Write-time dedup (A3) only compares against active facts in the same namespace, not archived ones
- With the 50-entry cap, the LLM comparison set stays small and fast regardless of total database size

**Why it's important:**

Every production memory system that works at scale has explicit lifecycle management. Mem0 does it at write time. CrewAI uses composite scoring with eviction. Zep archives with temporal invalidation. Without lifecycle management, memory systems degrade over months — not because the retrieval breaks, but because the signal-to-noise ratio drops as stale and duplicate entries accumulate. The caps and archival rules keep the active set small, relevant, and fast. The periodic consolidation catches what the automated rules miss.

---

### A8. Cross-Space and Deep Search

**What the user experiences today:**

Your Recruiting Agent can search conversations and memory within the Recruiting space. But when you ask "what did we decide about the compensation structure in the Finance conversations last month?" the agent can't look there — `search_conversations` requires a space ID and only searches within that space. The agent would have to say "I can only search within the Recruiting space."

For memory, the situation is slightly better — `read_memory` with no namespace searches all namespaces — but the agent doesn't know this is possible, and the search itself is basic substring matching. Searching for "auth module" won't find entries about "authentication system."

For conversation summaries, there's no search at all — the agent can list recent summaries but can't search their content. If you want to find which conversation discussed a specific decision, the agent has to load summaries one by one and read through them.

**What the user experiences after this change:**

You ask "what did we decide about compensation in the Finance space?" The agent searches across spaces and finds the relevant conversation summary. It can also search within its own space with much better accuracy — FTS5 full-text search instead of crude substring matching. "Auth module" finds entries about "authentication" because the search understands word boundaries and stemming.

The agent can also search conversation summary content directly: "Find all conversations where we discussed pricing" returns matched summaries across any space the agent has access to, ranked by relevance.

**How it works (simplified):**

**Tool upgrades:**
- `search_conversations(query, space_id?)` — `space_id` becomes optional. Omit it for cross-space search. Agents can search their own space by default, or any space they have read permission for.
- `search_summaries(query, space_id?)` — new tool. Searches conversation summary content (not just lists recent ones). Optional `space_id` for cross-space search.
- `read_memory(namespace?, key?, search?, category?)` — add `category` filter. Document in the tool description that omitting `namespace` searches all namespaces.
- All search tools return a relevance score from FTS5 BM25 ranking instead of arbitrary ordering.

**FTS5 indexes (aligns with Phase 4 plan):**
- `memory_entries.value` — facts become full-text searchable
- `conversation_messages.content` — conversation history becomes searchable
- `conversation_summaries.summary` — summary content becomes searchable
- Kept in sync via SQLite triggers on INSERT/UPDATE/DELETE

**Permission-scoped cross-space search:**
- When an agent searches without a `space_id`, results are filtered to spaces the agent has access to (via the `agent_spaces` join table)
- Odin can search all spaces (it's system-level)
- Space-scoped agents see only their own space(s) unless explicitly granted cross-space access

**Why it's important:**

The context assembler gives agents ~8000 tokens of automatic context. Everything beyond that depends on the agent's ability to search for it. If the search tools are weak (substring matching, single-space only, no summary search), then the 8000-token window is effectively the agent's entire knowledge — everything else is dark. Strong search tools make the full database accessible on demand, which means the 8000-token budget only needs to cover the "likely needed" context, not "everything the agent might ever need."

Cross-space search matters because real work crosses domain boundaries. A recruiting decision affects the project budget. A project deadline affects recruiting timelines. Agents that can only see their own space miss these connections.

---

## B. Context Safety

These capabilities prevent the silent failure mode where agents gradually lose important information as conversations get long and context gets compressed. This is the #1 complaint about long-running AI agents across the industry.

---

### B1. Mandatory Pre-Compaction Flush

**What the user experiences today:**

You have a long conversation with your Code Agent about redesigning the authentication module. Midway through, you discuss and agree on several specific decisions: use JWT tokens, 24-hour expiry, rotate refresh tokens. The conversation keeps going. At some point the system creates a checkpoint summary. The summary says "discussed auth redesign, decided on JWT-based approach." The specific decisions about expiry and refresh rotation aren't captured because summaries are lossy by design. Next session, the agent knows you chose JWT but not the specifics.

**What the user experiences after this change:**

Before any compression or summarization happens, the system tells the agent: "Save any important facts from this conversation to memory before I compress it." The agent uses its memory tools (A5) to write "auth tokens: JWT, 24-hour expiry, refresh token rotation" as persistent facts. Then the summary is generated. Even though the summary is lossy, the specific decisions survive as facts in memory. Next session, the agent knows the full picture.

**How it works (simplified):**

This is a mandatory pipeline stage, not an optional prompt. Before `monitor_context_usage()` triggers a checkpoint (at 70%) and before `close_session()` generates a final summary, the system injects a flush instruction: "Review this conversation for any important facts, decisions, or user preferences that haven't been saved to memory yet. Save them now using your memory tools." The agent processes this instruction, calls `save_fact` as many times as needed, and then the normal checkpoint/close flow continues.

OpenClaw implements this as a non-negotiable part of their compaction pipeline. It's their single most important safety mechanism against information loss.

**Why it's important:**

Summarization is inherently lossy. JetBrains research found that summaries "smooth over signs that the agent should stop" and can introduce subtle errors. The flush pipeline doesn't replace summarization — it supplements it by ensuring that high-value discrete facts survive even when the narrative summary loses detail. This is cheap insurance: one additional agent turn before each compression event.

---

### B2. Proactive Context Budget Enforcement

**What the user experiences today:**

You're in a long conversation. The system monitors context usage after each response. Most of the time this works fine. But occasionally, a particularly large response (agent reads several files, produces a detailed analysis) pushes context usage from 60% to 85% in a single turn. The system notices after the response is already generated and displayed. The next turn might degrade or fail. You see a suggestion to close and start a new conversation — but you're mid-thought.

**What the user experiences after this change:**

The system checks the budget before each message is sent to the LLM, not after. If the context is getting large, compression happens first — at a clean boundary (between complete exchanges, never splitting a tool-call sequence). The conversation continues smoothly. You never see a "context is almost full" warning that arrives too late. Long conversations just work, with the system managing its own resources transparently.

**How it works (simplified):**

Before every `query()` call, the session manager estimates total context size (system prompt + memory + conversation history + pending message). If it exceeds 70% of the context window:
1. Trigger the pre-compaction flush (B1) to save important facts
2. Compress older conversation turns at a turn boundary (keeping the most recent 2-3 turns verbatim, replacing older turns with a summary)
3. Then proceed with the LLM call

The key detail: compression happens at turn boundaries — complete user message + agent response pairs. Never in the middle of a tool-call sequence. This preserves conversation coherence.

**Why it's important:**

Reactive monitoring means the system always discovers problems one turn too late. Proactive enforcement means problems are prevented before they affect the user. PicoClaw implements this and it's one of their key architectural advantages. The cost is one token-estimation check per turn — negligible.

---

### B3. Recent Turn Preservation (Observation Masking)

**What the user experiences today:**

When conversation context gets compressed, the system generates a summary of the older parts. This summary is good but inherently lossy — it captures themes and decisions but not exact wording, specific examples, or nuanced reasoning. If you referenced something specific from 5 turns ago, the agent might not have the exact details anymore after compression.

**What the user experiences after this change:**

The most recent 2-3 complete exchanges (your message + agent response) are always kept verbatim — never summarized. Only older exchanges get compressed. This means the immediate working context — the thread you're actively pulling on — stays intact. The agent always has perfect recall of what just happened, even if older history has been condensed.

**How it works (simplified):**

During context compression (triggered by B2), the system applies "observation masking" instead of full summarization:
- **Keep verbatim:** The 2-3 most recent user-agent exchange pairs
- **Compress:** Everything older, into a summary that captures decisions, open questions, and key facts
- **Extract:** Important discrete facts from the compressed section into persistent memory (via B1)

JetBrains research found that "keeping a window of the latest 10 turns gave the best balance" — a 2.6% improvement in task completion while being 52% cheaper than full summarization approaches. The observation masking approach outperformed recursive summarization.

**Why it's important:**

The immediate conversational context — what you just discussed, what the agent just did, what you're about to ask about — is the highest-value content in the context window. Summarizing it loses essential detail. Keeping it verbatim while compressing older history is a strictly better strategy than uniform compression.

---

### B4. Summary Consolidation

**What the user experiences today:**

After 3 months of active use, your Project space has 40+ conversation summaries. The context assembler can only fit the 8-10 most recent in its token budget. When you start a new conversation, the agent has detailed knowledge of the last few weeks but no awareness of what happened in the first two months — unless it explicitly searches. You ask "what's the overall trajectory of this project?" and the agent can only speak to recent activity.

**What the user experiences after this change:**

When a space accumulates enough conversation history (20+ unconsolidated summaries), the system automatically generates a "meta-summary" — a condensed overview of all those conversations. Example: "From January to March: shipped the API redesign, hired two candidates for frontend, resolved the auth module compliance issue. Key decisions: moved to JWT, chose Tailwind v4, decided against GraphQL. Open threads: mobile responsiveness, backup automation." This meta-summary replaces the individual older summaries in context assembly (the originals remain in the database for search). Now the agent has months of project awareness in a compact block, plus detailed knowledge of recent conversations.

You can also trigger consolidation manually from the space settings ("Consolidate conversation history") — useful if you want a clean slate before a major project shift, or if you want to consolidate earlier than the automatic threshold.

**How it works (simplified):**

**Trigger:** Automated, threshold-based. When the count of unconsolidated summaries for a space exceeds 20, consolidation runs automatically the next time a conversation closes in that space (piggybacks on the close flow rather than requiring a separate background scheduler). A space with 3 conversations per week hits the threshold in ~7 weeks. A quiet space with 1 conversation per month doesn't trigger unnecessary consolidation. The user can also trigger it manually from space settings at any time.

**Process:** The system reads all unconsolidated summaries for the space, groups them chronologically, and generates a single meta-summary using the LLM. The meta-summary is stored as a special `conversation_summary` entry with a flag (`is_meta_summary = true`). The individual summaries that were consolidated are marked with a `consolidated_into` reference pointing to the meta-summary (they remain in the database for search but are excluded from context assembly). During context assembly, the meta-summary takes priority as the first episodic memory entry, followed by the most recent unconsolidated individual summaries.

**Successive consolidation:** When a second round of 20 summaries accumulates after the first consolidation, the system generates a new meta-summary that covers both the old meta-summary and the new individual summaries. The old meta-summary is itself marked as consolidated. This means the system always has one current meta-summary covering the full history, regardless of how many rounds have occurred.

**Why it's important:**

Conversation summaries grow linearly with usage. Without consolidation, agents develop a "recency horizon" — they know the last 2-3 weeks well but are blind to anything older. For project spaces with months of history, this horizon means agents can't help with questions about the project's overall direction, past decisions, or long-term patterns. Consolidation extends the horizon to the full project lifetime within a fixed token budget.

---

## C. Agent Control

These capabilities give users real-time control over what agents are doing, especially for background and delegated work.

---

### C1. Mid-Task Steering

**What the user experiences today:**

You tell your Research Agent to "go research competitor X's pricing strategy." The agent starts working in the background. You watch the activity log and realize it's researching the wrong company (Competitor X Inc. instead of Competitor X Corp.), or it's spending all its time on product features instead of pricing. Your options: wait for it to finish and get useless results, or cancel the entire task and start over. Either way, the work done so far is wasted.

**What the user experiences after this change:**

While the agent is working, you can send it a message: "Wrong company — I mean Competitor X Corp, the SaaS company." The agent receives this between tool calls. It finishes whatever tool is currently running (you don't lose partial results), skips any remaining queued tool calls, reads your correction, and adjusts course. The task continues with the right focus. No restart needed. The partial work is preserved.

This also works for interactive conversations where the agent is in the middle of a long tool-use sequence. Instead of waiting for the agent to finish reading 15 files, you can say "stop — I found the answer, it's in auth.py" and redirect it immediately.

**How it works (simplified):**

A "steering queue" sits between the user and the running agent session. When a steering message arrives:
1. The currently-executing tool call finishes (no interruption mid-tool)
2. Any remaining queued tool calls for the current turn are skipped
3. The steering message is injected as the next user message
4. The agent processes it and continues from there

PicoClaw implements this with a thread-safe queue, max 10 messages per scope, and two dequeue modes (one-at-a-time for corrections, drain-all for "stop everything" commands).

**Why it's important:**

Background delegation is one of OpenLoop's key value propositions ("tell an agent to go do something, come back when it's done"). But delegation without course-correction means any wrong turn wastes the entire task. Steering transforms background delegation from "fire and pray" to "fire and guide." This is the difference between delegating to a junior employee you can't reach and one who checks their phone.

---

## D. Capability Persistence

These capabilities let agents build reusable knowledge artifacts that persist as first-class objects — not just memory entries, but structured procedures and multi-step workflows.

---

### D1. Multi-Step Workflow Tracking

**What the user experiences today:**

You delegate a complex task: "Research the top 5 competitors, summarize their pricing, and create a comparison board item for each." The agent creates a single background task. If it fails halfway through (network error, rate limit, context overflow), you see "task failed" with partial results. There's no record of which competitors were completed and which weren't. Restarting means redoing everything from scratch — including the work that already succeeded.

**What the user experiences after this change:**

Complex delegations are broken into tracked steps. The background task shows: "Step 1/5: Researching Competitor A... done. Step 2/5: Researching Competitor B... in progress." If it fails at step 3, you see exactly where it stopped. You can resume from step 3, not from the beginning. Each completed step's results are preserved (board items already created, research notes already saved).

The task detail view shows a timeline: each step with its status, duration, and output summary. For parent tasks that spawn sub-agents, you can see the hierarchy: "Research task → spawned 5 sub-agents → 3 completed, 1 running, 1 queued."

**How it works (simplified):**

Extends the existing `background_tasks` table with workflow tracking: `current_step`, `total_steps`, `step_results` (JSON array of completed step outcomes), and `parent_task_id` for sub-task hierarchies. When an agent delegates sub-tasks, each gets its own `background_task` record linked to the parent. The UI aggregates these into a single workflow view.

OpenClaw's `flow_runs` table implements this pattern: flows track `current_step`, `waiting_on_task_id`, `blocked_task_id`, and `outputs_json`. Their audit system detects stale tasks (>10min queued) and stuck tasks (>30min running) — health checks that prevent silent failures.

**Why it's important:**

The current single-task model breaks down for anything non-trivial. Real work is multi-step. When multi-step tasks fail (and they will — rate limits, network issues, context overflow), the user needs to know what was completed and what wasn't. Without step tracking, every failure means a full restart. With it, failures are recoverable. This is the difference between "the task failed" and "steps 1-3 succeeded, step 4 failed because of X, here's what to do next."

---

## Priority and Timing

### Now — Before Phase 3 Starts

These are low-disruption backend changes to code that already exists:

| Item | What Changes | Effort |
|---|---|---|
| **B1** Pre-compaction flush | Add one prompt step before checkpoint/close logic in session manager | Small |
| **B2** Proactive budget check | Add pre-call estimation to session manager's send flow | Small |
| **A5** Agent memory tools | Enhance existing MCP tools, add memory management instructions to agent prompts | Small-Medium |
| **A6** Context ordering | Reorder existing context assembly output | Small |

### Phase 3-4 — With Frontend Work

These need schema changes and/or new UI surfaces:

| Item | What Changes | Effort |
|---|---|---|
| **A1** Procedural memory | New `behavioral_rules` table, context assembly changes, new UI section in agent settings | Medium |
| **A2** Temporal facts | Add `valid_from`/`valid_until` to `memory_entries`, modify write-time logic | Medium |
| **A3** Write-time dedup | Add LLM comparison step to memory write flow | Medium |
| **B3** Observation masking | Modify compression strategy in session manager | Small |
| **C1** Mid-task steering | Steering queue in session manager, message input on background task UI | Medium |

### Phase 4 — With Search Infrastructure (FTS5)

These align with the existing Phase 4 plan for FTS5 and document management:

| Item | What Changes | Effort |
|---|---|---|
| **A8** Cross-space and deep search | FTS5 indexes on memory/messages/summaries, upgrade search MCP tools, cross-space permissions | Medium |

### Phase 6-7 — Polish and Scaling

These become important as data accumulates:

| Item | What Changes | Effort |
|---|---|---|
| **A4** Retrieval scoring | New fields on `memory_entries`, scoring formula in context assembler | Medium |
| **A7** Memory lifecycle management | Namespace caps with eviction, auto-archival rules, periodic LLM-driven fact consolidation | Medium |
| **B4** Summary consolidation | Threshold-triggered meta-summary generation (auto at 20 summaries, or manual) | Small-Medium |
| **D1** Workflow tracking | Extend `background_tasks` schema, parent-child linking, step tracking UI | Medium |

### Post-Launch (P1)

| Item | What Changes | Effort |
|---|---|---|
| **Hybrid search** (not numbered — deferred) | Embedding infrastructure, vector storage, hybrid retrieval | Large |

---

## What This Does NOT Cover

These were evaluated and deliberately excluded:

- **Container isolation** (NanoClaw) — sandboxing agent execution. Significant infrastructure. Revisit post-launch based on real permission violation patterns.
- **Smart model routing** (PicoClaw) — per-message model selection by complexity. Odin already routes at the conversation level. Marginal gain for added complexity.
- **Pluggable context engine** (OpenClaw) — swappable context assembly strategies. Over-engineered for a single-user tool. Per-space configuration is simpler.
- **Knowledge graph** (CoWork-OS, Zep) — entity-relationship memory with graph traversal. Heavy. Revisit at P2 based on actual CRM usage.
- **Provider-side cache hints** (PicoClaw) — cacheable prompt sections. Performance optimization, not a capability. Add later.
- **Input provenance** (OpenClaw) — tagging messages with origin session/channel. Useful for debugging multi-agent flows but not critical for single-user.
- **Recipe/skill persistence** (OpenClaw skill-creator, Voyager) — saving multi-step workflows as reusable named procedures. Evaluated and rejected: behavioral rules (procedural memory) and well-categorized facts achieve the same outcome more flexibly. A rigid step sequence is redundant when the agent has good rules and domain knowledge — the LLM can construct the right workflow adaptively. If specific workflows consistently underperform despite good rules and facts, revisit.

---

## How These Relate to Each Other

The items aren't independent — they form a coherent system:

```
User corrects agent
        │
        ▼
 A1 (Procedural Memory) ◄── captures correction as behavioral rule
        │
        ▼
 A5 (Memory Tools) ◄── agent saves facts + rules using enhanced tools
        │
        ▼
 A3 (Write-Time Dedup) ◄── prevents duplicate/contradictory entries
        │
        ▼
 A2 (Temporal Facts) ◄── superseded facts keep history with timestamps
        │
        ▼
 A7 (Lifecycle Mgmt) ◄── caps, archival, and consolidation keep memory lean
        │
        ▼
 A4 (Retrieval Scoring) ◄── best facts surface during context assembly
        │
        ▼
 A6 (Context Ordering) ◄── facts placed for maximum model attention
        │
        ▼
 A8 (Deep Search) ◄── agents find details beyond the context window
        │
        ▼
 B1 (Pre-Compaction Flush) ◄── facts saved before any compression
        │
        ▼
 B2 (Budget Enforcement) ◄── compression happens proactively, cleanly
        │
        ▼
 B3 (Observation Masking) ◄── recent turns kept verbatim during compression
        │
        ▼
 B4 (Summary Consolidation) ◄── older history condensed, not lost
```

The memory writes flow down. The context reads flow up. The safety mechanisms protect the transition between them. A7 keeps the active memory set small and relevant over time. A8 ensures everything beyond the context window is still reachable. And the agent control (C1) and capability persistence (D1, D2) operate alongside the whole system to make delegated work reliable and improvable.

---

## Competitive Context

No existing tool covers OpenLoop's full scope. With these additions, OpenLoop would have:

- **Memory architecture on par with Letta** (the gold standard) — four-tier, agent-managed, temporally-aware, with write-time dedup
- **Context safety exceeding OpenClaw** — proactive budget enforcement + flush pipeline + observation masking
- **Agent learning that matches CrewAI/LangMem** — procedural memory from corrections, behavioral rules that persist across sessions
- **Workflow tracking matching OpenClaw's task/flow system** — multi-step tracking with recovery

Combined with OpenLoop's unique value (integrated task management + multi-agent orchestration + proactive system), this creates a product that is measurably more capable than anything currently available.

---

## Sources

**Academic/Research:**
- MemGPT paper (Packer et al., 2023) — two-tier memory architecture
- "Lost in the Middle" (Liu et al., 2023) — context position effects on accuracy
- Voyager (Wang et al., 2023) — skill library for procedural learning
- Zep/Graphiti paper (2025) — temporal knowledge graphs, 18.5% retrieval improvement
- Mem0 paper (2025) — ADD/UPDATE/DELETE/NOOP, 26% quality improvement
- ReMe framework (2025) — procedural memory, model-scale substitution
- "Memory in the Age of AI Agents" survey (Dec 2025) — four-type taxonomy
- JetBrains research (Dec 2025) — observation masking vs. summarization evidence
- Hindsight (Dec 2025) — confidence-scored opinions, four-network architecture

**Industry/Production:**
- Anthropic: "Effective Context Engineering for AI Agents" — context ordering, just-in-time loading
- Anthropic: "Effective Harnesses for Long-Running Agents" — progress files, identity persistence
- OpenAI Agents SDK Cookbook — memory precedence hierarchy, "forgetting is essential"
- LangMem SDK — procedural memory via prompt evolution
- CrewAI Cognitive Memory — composite scoring, human feedback distillation
- YourMemory — Ebbinghaus decay implementation, 34% vs 18% recall improvement

**Open Source Systems:**
- OpenClaw — pre-compaction flush, pluggable context engine, skill persistence, task/flow registry
- PicoClaw — proactive budget enforcement, mid-turn steering, provider cache hints
- Nanobot — LLM-as-memory-manager, iterative consolidation
- NanoClaw — CLAUDE.md as memory, container isolation
