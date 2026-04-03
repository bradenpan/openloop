# Claude Agent Configuration — OpenLoop

Read and follow `agents.md` in this directory for all behavioral rules, memory guidelines, and error handling.

Everything below is Claude Code-specific configuration that would change if the underlying model/runtime changes.

## Execution Model

You are invoked via the Claude Agent SDK's `query()` function under a Claude Max subscription. Your session is a long-lived Claude Code CLI process managed by OpenLoop's AgentRunner.

- **Interactive conversations:** The user sends messages via the UI. Each message is routed to your session via `query(resume=session_id)`. You respond in a streaming fashion.
- **Background delegation:** You receive a single instruction and work autonomously. No user interaction. Write results via MCP tools.
- **Session resume:** If your session is interrupted (crash, restart), the system may resume it or start a new session with your conversation summary injected as context.

## Permission Mode

Your session's permission behavior is controlled by OpenLoop's Permission Enforcer, not by Claude Code's built-in permission modes:

- **MCP tool calls** (OpenLoop tools like `create_todo`, `write_memory`, etc.) are always allowed — they go through OpenLoop's own permission layer, not the CLI's.
- **File operations** (Read, Write, Edit, Glob, Grep) are checked against your agent's permission matrix. The Permission Enforcer extracts the file path and matches it against your allowed resource patterns.
- **Bash commands** default to "Requires approval" for all agents. The user will be prompted before any shell command executes.
- **System guardrails** silently deny access to blocked paths (`~/.ssh`, `~/.aws`, `~/.claude`, `.env`, `credentials.json`, `openloop.db`). You'll receive a denial message — don't retry, report the blocker or work around it.

## Context Injection

OpenLoop assembles your prompt from: `agents.md` + your agent's system prompt + space context (board state, conversation summaries, facts) + tool documentation. This is injected via `append_system_prompt`. You don't need to fetch these yourself — they're in your system prompt when the session starts.

## Model Selection

Your default model is set in your agent configuration (typically Sonnet). The user can override the model per conversation. You don't need to be aware of which model you're running on — just do your best work.
