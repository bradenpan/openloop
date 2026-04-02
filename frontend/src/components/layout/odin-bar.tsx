import { useCallback, useEffect, useRef, useState } from 'react';
import { $api } from '../../api/hooks';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { useUIStore } from '../../stores/ui-store';

interface OdinMessage {
  role: 'user' | 'assistant';
  content: string;
}

export function OdinBar() {
  const expanded = useUIStore((s) => s.odinExpanded);
  const toggle = useUIStore((s) => s.toggleOdin);

  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<OdinMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const sendToOdin = $api.useMutation('post', '/api/v1/odin/message');

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  // Listen for Odin SSE events (Odin uses a system-level conversation, no conversation_id filter)
  useSSEEvent(
    useCallback((event: SSEEvent) => {
      if (event.type === 'token') {
        setIsStreaming(true);
        setStreamingContent((prev) => (prev ?? '') + event.content);
      }
      if (event.type === 'error') {
        setIsStreaming(false);
        setStreamingContent(null);
      }
    }, []),
  );

  const handleSend = () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setInput('');
    setStreamingContent(null);
    setIsStreaming(true);

    sendToOdin.mutate(
      { body: { content: text } },
      {
        onSuccess: () => {
          // Odin response will stream via SSE
        },
        onError: () => {
          setIsStreaming(false);
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: 'Failed to reach Odin. Is the backend running?' },
          ]);
        },
      },
    );
  };

  // When streaming finishes (detected by absence of new tokens), persist the streamed message
  // For now, we finalize when the user sends the next message or after a timeout
  useEffect(() => {
    if (!isStreaming || streamingContent === null) return;
    // Simple approach: if no new token in 2 seconds, finalize
    const timer = setTimeout(() => {
      if (streamingContent) {
        setMessages((prev) => [...prev, { role: 'assistant', content: streamingContent }]);
        setStreamingContent(null);
        setIsStreaming(false);
      }
    }, 2000);
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
          {messages.map((msg, i) => (
            <div key={i} className={`mb-2 text-sm ${msg.role === 'user' ? '' : 'text-muted'}`}>
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
