import { useEffect, useRef } from 'react';
import { $api } from '../../api/hooks';
import type { ToolCallState, ApprovalRequestState } from './conversation-panel';
import { ToolCallAccordion } from './tool-call-accordion';
import { ApprovalRequest } from './approval-request';

interface MessageListProps {
  conversationId: string;
  streamingContent: string | null;
  streamingToolCalls: ToolCallState[];
  approvalRequests: ApprovalRequestState[];
  onApprovalRespond: (requestId: string, approved: boolean) => void;
}

export function MessageList({
  conversationId,
  streamingContent,
  streamingToolCalls,
  approvalRequests,
  onApprovalRespond,
}: MessageListProps) {
  const { data: messages } = $api.useQuery('get', '/api/v1/conversations/{conversation_id}/messages', {
    params: { path: { conversation_id: conversationId } },
  });

  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change or streaming content updates
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent, streamingToolCalls.length, approvalRequests.length]);

  const isStreaming = streamingContent !== null;

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Persisted messages */}
      {messages?.map((msg) => {
        const isUser = msg.role === 'user';
        return (
          <div
            key={msg.id}
            className={`px-4 py-4 ${isUser ? 'bg-surface' : 'bg-raised'}`}
          >
            <div className="text-xs font-medium text-muted mb-1.5">
              {isUser ? 'You' : 'Assistant'}
            </div>
            <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
              {msg.content}
            </div>
          </div>
        );
      })}

      {/* Streaming assistant response */}
      {isStreaming && (
        <div className="px-4 py-4 bg-raised">
          <div className="text-xs font-medium text-muted mb-1.5">Assistant</div>

          {/* Tool calls during streaming */}
          {streamingToolCalls.map((tc) => (
            <ToolCallAccordion
              key={tc.id}
              toolName={tc.toolName}
              status={tc.status}
              resultSummary={tc.resultSummary}
            />
          ))}

          {/* Streamed text content */}
          {streamingContent && (
            <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
              {streamingContent}
              <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 align-text-bottom animate-pulse" />
            </div>
          )}

          {/* Show cursor even when no text yet (tool calls only) */}
          {!streamingContent && streamingToolCalls.length > 0 && (
            <div className="text-sm text-muted">
              <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 align-text-bottom animate-pulse" />
            </div>
          )}
        </div>
      )}

      {/* Inline approval requests */}
      {approvalRequests.map((req) => (
        <div key={req.requestId} className="px-4 py-2 bg-raised">
          <ApprovalRequest
            requestId={req.requestId}
            toolName={req.toolName}
            resource={req.resource}
            operation={req.operation}
            onRespond={onApprovalRespond}
          />
        </div>
      ))}

      {/* Empty state */}
      {(!messages || messages.length === 0) && !isStreaming && (
        <div className="flex items-center justify-center h-full text-muted text-sm">
          No messages yet. Send a message to get started.
        </div>
      )}

      {/* Bottom sentinel for auto-scroll */}
      <div ref={bottomRef} />
    </div>
  );
}
