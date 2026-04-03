import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { ConversationHeader } from './conversation-header';
import { MessageList } from './message-list';
import { MessageInput } from './message-input';

export interface ToolCallState {
  /** Synthetic ID: `${toolName}-${index}` */
  id: string;
  toolName: string;
  status: 'started' | 'completed' | 'failed';
  resultSummary?: string;
}

export interface ApprovalRequestState {
  requestId: string;
  toolName: string;
  resource: string;
  operation: string;
}

interface ConversationPanelProps {
  conversationId: string;
  onClose?: () => void;
}

export function ConversationPanel({ conversationId, onClose }: ConversationPanelProps) {
  const queryClient = useQueryClient();

  // Streaming state
  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [streamingToolCalls, setStreamingToolCalls] = useState<ToolCallState[]>([]);
  const [approvalRequests, setApprovalRequests] = useState<ApprovalRequestState[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  // Track tool call count for generating synthetic IDs
  const toolCallCountRef = useRef(0);

  // Send message mutation
  const sendMessage = $api.useMutation('post', '/api/v1/conversations/{conversation_id}/messages');

  // Finalize streaming: clear state and refetch messages
  const finalizeStreaming = useCallback(() => {
    setStreamingContent(null);
    setStreamingToolCalls([]);
    setIsStreaming(false);
    toolCallCountRef.current = 0;
    // Refetch persisted messages to pick up the assistant response saved by the backend
    queryClient.invalidateQueries({
      queryKey: ['get', '/api/v1/conversations/{conversation_id}/messages'],
    });
  }, [queryClient]);

  // Handle SSE events scoped to this conversation
  useSSEEvent(
    useCallback(
      (event: SSEEvent) => {
        // Filter by conversation_id where present
        if ('conversation_id' in event && event.conversation_id !== conversationId) return;

        switch (event.type) {
          case 'token': {
            setIsStreaming(true);
            setStreamingContent((prev) => (prev ?? '') + event.content);
            break;
          }

          case 'tool_call': {
            setIsStreaming(true);
            if (event.status === 'started') {
              const id = `${event.tool_name}-${toolCallCountRef.current++}`;
              setStreamingToolCalls((prev) => [
                ...prev,
                { id, toolName: event.tool_name, status: 'started' },
              ]);
            } else {
              // Update the most recent matching tool call with the new status
              setStreamingToolCalls((prev) => {
                const idx = [...prev].reverse().findIndex(
                  (tc) => tc.toolName === event.tool_name && tc.status === 'started',
                );
                if (idx === -1) return prev;
                const realIdx = prev.length - 1 - idx;
                const updated = [...prev];
                updated[realIdx] = { ...updated[realIdx], status: event.status };
                return updated;
              });
            }
            break;
          }

          case 'tool_result': {
            // Attach result summary to the most recent matching tool call
            setStreamingToolCalls((prev) => {
              const idx = [...prev].reverse().findIndex(
                (tc) => tc.toolName === event.tool_name,
              );
              if (idx === -1) return prev;
              const realIdx = prev.length - 1 - idx;
              const updated = [...prev];
              updated[realIdx] = { ...updated[realIdx], resultSummary: event.result_summary };
              return updated;
            });
            break;
          }

          case 'approval_request': {
            setApprovalRequests((prev) => [
              ...prev,
              {
                requestId: event.request_id,
                toolName: event.tool_name,
                resource: event.resource,
                operation: event.operation,
              },
            ]);
            break;
          }

          case 'stream_end': {
            finalizeStreaming();
            break;
          }

          case 'error': {
            // Error terminates streaming
            if (isStreaming) {
              finalizeStreaming();
            }
            break;
          }
        }
      },
      [conversationId, isStreaming, finalizeStreaming],
    ),
  );

  // Detect streaming completion: when the messages query returns a new assistant
  // message that matches our streaming content, the backend has persisted it.
  // We use the query's data updates to detect this.
  const { data: messages } = $api.useQuery(
    'get',
    '/api/v1/conversations/{conversation_id}/messages',
    { params: { path: { conversation_id: conversationId } } },
  );

  // Detect streaming completion: when the messages query returns a new assistant
  // message, the backend has persisted it — finalize streaming state.
  const prevMessageCountRef = useRef(messages?.length ?? 0);
  useEffect(() => {
    if (!messages) return;
    if (messages.length > prevMessageCountRef.current) {
      const lastMsg = messages[messages.length - 1];
      if (isStreaming && lastMsg.role === 'assistant') {
        finalizeStreaming();
      }
    }
    prevMessageCountRef.current = messages.length;
  }, [messages, isStreaming, finalizeStreaming]);

  // Fallback: if stream_end is never received (network issue, backend bug),
  // finalize after 10 seconds of silence (no new tokens)
  useEffect(() => {
    if (!isStreaming || streamingContent === null) return;
    const timer = setTimeout(() => {
      finalizeStreaming();
    }, 10_000);
    return () => clearTimeout(timer);
  }, [isStreaming, streamingContent, finalizeStreaming]);

  const handleSend = (content: string) => {
    // Reset streaming state for the new response cycle
    setStreamingContent(null);
    setStreamingToolCalls([]);
    setApprovalRequests([]);
    toolCallCountRef.current = 0;

    sendMessage.mutate(
      {
        params: { path: { conversation_id: conversationId } },
        body: { content },
      },
      {
        onSuccess: () => {
          // Refetch to show the persisted user message immediately
          queryClient.invalidateQueries({
            queryKey: ['get', '/api/v1/conversations/{conversation_id}/messages'],
          });
          // Mark as streaming — the backend background task will start producing SSE events
          setIsStreaming(true);
        },
      },
    );
  };

  const handleApprovalRespond = async (requestId: string, approved: boolean) => {
    // TODO: This endpoint needs to be created on the backend.
    // The permission enforcer polls the DB for status changes on the PermissionRequest row,
    // so this PATCH just updates the row's status field.
    try {
      await fetch(`/api/v1/agents/permission-requests/${requestId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: approved ? 'approved' : 'denied' }),
      });
    } catch (err) {
      console.error('Failed to respond to approval request:', err);
    }

    // Remove from local state regardless — the backend will resolve via polling
    setApprovalRequests((prev) => prev.filter((r) => r.requestId !== requestId));
  };

  const inputDisabled = isStreaming || sendMessage.isPending;

  return (
    <div className="flex flex-col h-full bg-background">
      <ConversationHeader conversationId={conversationId} onClose={onClose} />
      <MessageList
        conversationId={conversationId}
        streamingContent={streamingContent}
        streamingToolCalls={streamingToolCalls}
        approvalRequests={approvalRequests}
        onApprovalRespond={handleApprovalRespond}
      />
      <MessageInput
        conversationId={conversationId}
        disabled={inputDisabled}
        onSend={handleSend}
      />
    </div>
  );
}
