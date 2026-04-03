import { useCallback, useEffect, useRef, useState } from 'react';
import { $api } from '../../api/hooks';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { useUIStore } from '../../stores/ui-store';

interface OdinMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

let nextMsgId = 1;
function msgId(): string {
  return `odin-msg-${nextMsgId++}`;
}

export function OdinBar() {
  const expanded = useUIStore((s) => s.odinExpanded);
  const toggle = useUIStore((s) => s.toggleOdin);

  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<OdinMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pendingSendRef = useRef(false);

  const sendToOdin = $api.useMutation('post', '/api/v1/odin/message');

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  // Listen for SSE events scoped to Odin's conversation
  useSSEEvent(
    useCallback(
      (event: SSEEvent) => {
        // Before the first message, conversationId is null — ignore events unless a send is pending
        if (conversationId === null && !pendingSendRef.current) return;
        // Only process events that belong to Odin's conversation (skip check while awaiting first conversationId)
        if (conversationId !== null && 'conversation_id' in event && event.conversation_id !== conversationId) return;

        if (event.type === 'token') {
          setIsStreaming(true);
          setStreamingContent((prev) => (prev ?? '') + event.content);
        }
        if (event.type === 'stream_end') {
          setStreamingContent((prev) => {
            if (prev) {
              setMessages((msgs) => [...msgs, { id: msgId(), role: 'assistant', content: prev }]);
            }
            return null;
          });
          setIsStreaming(false);
        }
        if (event.type === 'error') {
          setIsStreaming(false);
          setStreamingContent(null);
        }
      },
      [conversationId],
    ),
  );

  const handleSend = () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    setMessages((prev) => [...prev, { id: msgId(), role: 'user', content: text }]);
    setInput('');
    setStreamingContent(null);
    setIsStreaming(true);

    pendingSendRef.current = true;
    sendToOdin.mutate(
      { body: { content: text } },
      {
        onSuccess: (data) => {
          // Track Odin's conversation so we only process its SSE events
          setConversationId(data.conversation_id);
          pendingSendRef.current = false;
        },
        onError: () => {
          pendingSendRef.current = false;
          setIsStreaming(false);
          setMessages((prev) => [
            ...prev,
            { id: msgId(), role: 'assistant', content: 'Failed to reach Odin. Is the backend running?' },
          ]);
        },
      },
    );
  };

  // Fallback: if stream_end is never received (network issue, backend bug),
  // finalize after 10 seconds of silence
  useEffect(() => {
    if (!isStreaming || streamingContent === null) return;
    const timer = setTimeout(() => {
      setStreamingContent((prev) => {
        if (prev) {
          setMessages((msgs) => [...msgs, { id: msgId(), role: 'assistant', content: prev }]);
        }
        return null;
      });
      setIsStreaming(false);
    }, 10_000);
    return () => clearTimeout(timer);
  }, [isStreaming, streamingContent]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="bg-surface border-t border-border">
      {/* Expanded chat area */}
      {expanded && (
        <div className="border-b border-border px-4 py-3 max-h-80 overflow-auto">
          {messages.length === 0 && !streamingContent && (
            <p className="text-sm text-muted italic">
              Ask Odin anything — create tasks, navigate spaces, or get help.
            </p>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className={`mb-2 text-sm ${msg.role === 'user' ? '' : 'text-muted'}`}>
              <span className="text-xs font-semibold text-muted mr-2">
                {msg.role === 'user' ? 'You' : 'Odin'}
              </span>
              <span className="whitespace-pre-wrap">{msg.content}</span>
            </div>
          ))}
          {streamingContent && (
            <div className="mb-2 text-sm text-muted">
              <span className="text-xs font-semibold text-muted mr-2">Odin</span>
              <span className="whitespace-pre-wrap">{streamingContent}</span>
              <span className="animate-pulse ml-0.5">|</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      )}

      {/* Input bar */}
      <div className="flex items-center gap-2 px-4 py-2">
        <button
          onClick={toggle}
          className="bg-primary text-primary-foreground rounded-md px-2.5 py-1 text-sm font-bold hover:bg-primary-hover transition-colors cursor-pointer"
          aria-label={expanded ? 'Collapse Odin' : 'Expand Odin'}
        >
          {expanded ? '\u2212' : '+'}
        </button>

        {!expanded && (
          <button
            onClick={toggle}
            className="flex-1 text-left text-sm text-muted hover:text-foreground transition-colors cursor-pointer"
          >
            Ask Odin anything...
          </button>
        )}

        {expanded && (
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            data-odin-input
            className="flex-1 bg-raised border border-border rounded-md px-3 py-1.5 text-sm text-foreground placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary"
            placeholder="Ask Odin anything..."
            disabled={isStreaming}
            autoFocus
          />
        )}

        <button className="text-xs font-semibold px-3 py-1.5 rounded-md border border-border text-muted hover:text-primary hover:border-primary transition-colors cursor-pointer whitespace-nowrap">
          Opus &#9889;
        </button>
      </div>
    </div>
  );
}
