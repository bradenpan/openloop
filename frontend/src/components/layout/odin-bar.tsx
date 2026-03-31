import { useState, useRef, useEffect } from "react";
import { useUIStore } from "@/stores/ui-store";

function OdinBar() {
  const odinExpanded = useUIStore((s) => s.odinExpanded);
  const setOdinExpanded = useUIStore((s) => s.setOdinExpanded);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Array<{ role: "user" | "assistant"; text: string }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (odinExpanded && inputRef.current) {
      inputRef.current.focus();
    }
  }, [odinExpanded]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;

    setMessages((prev) => [
      ...prev,
      { role: "user", text },
      { role: "assistant", text: "Odin is not connected yet. This is a placeholder response." },
    ]);
    setInput("");
  }

  return (
    <div
      className={[
        "border-b border-[var(--color-border-default)] bg-[var(--color-bg-secondary)]",
        "transition-[height] duration-[var(--transition-normal)]",
        "flex flex-col overflow-hidden",
      ].join(" ")}
      style={{ height: odinExpanded ? "320px" : "var(--odin-bar-height)" }}
    >
      {/* Expanded chat area */}
      {odinExpanded && (
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full">
              <p className="text-[var(--text-sm)] text-[var(--color-text-tertiary)] font-mono">
                // Odin awaits your command
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={[
                "text-[var(--text-sm)] px-3 py-2 rounded-[var(--radius-sm)] max-w-[80%]",
                msg.role === "user"
                  ? "ml-auto bg-[var(--color-accent-muted)] text-[var(--color-text-primary)]"
                  : "mr-auto bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] font-mono",
              ].join(" ")}
            >
              {msg.text}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Input bar */}
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-2 px-4 shrink-0"
        style={{ height: "var(--odin-bar-height)" }}
      >
        {/* Expand/collapse toggle */}
        <button
          type="button"
          onClick={() => setOdinExpanded(!odinExpanded)}
          className="shrink-0 p-1 rounded-[var(--radius-sm)] text-[var(--color-accent-text)] hover:bg-[var(--color-accent-muted)] transition-colors cursor-pointer"
          aria-label={odinExpanded ? "Collapse Odin" : "Expand Odin"}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            className={[
              "transition-transform duration-[var(--transition-fast)]",
              odinExpanded ? "rotate-180" : "",
            ].join(" ")}
          >
            <path
              d="M4 10l4-4 4 4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>

        {/* Odin label */}
        <span className="text-[var(--text-xs)] font-mono font-semibold text-[var(--color-accent-text)] shrink-0 select-none">
          ODIN
        </span>

        {/* Input */}
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask Odin anything..."
          className={[
            "flex-1 h-8 px-3 rounded-[var(--radius-sm)]",
            "bg-[var(--color-bg-primary)] border border-[var(--color-border-default)]",
            "text-[var(--text-sm)] text-[var(--color-text-primary)]",
            "placeholder:text-[var(--color-text-tertiary)]",
            "focus:outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]",
            "transition-colors",
          ].join(" ")}
          onFocus={() => {
            if (!odinExpanded) setOdinExpanded(true);
          }}
        />

        {/* Send button */}
        <button
          type="submit"
          disabled={!input.trim()}
          className={[
            "shrink-0 h-8 px-3 rounded-[var(--radius-sm)]",
            "text-[var(--text-sm)] font-medium",
            "bg-[var(--color-accent)] text-[var(--color-text-inverse)]",
            "hover:bg-[var(--color-accent-hover)]",
            "disabled:opacity-40 disabled:pointer-events-none",
            "transition-colors cursor-pointer",
          ].join(" ")}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path
              d="M2 8l10-5-3 5 3 5L2 8z"
              fill="currentColor"
            />
          </svg>
        </button>
      </form>
    </div>
  );
}

export { OdinBar };
