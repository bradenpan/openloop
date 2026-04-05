import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { ConversationHeader } from './conversation-header';
import { AutonomousHeader } from './autonomous-header';
import { TaskListSidebar } from './task-list-sidebar';
import { DelegationTree } from './delegation-tree';
import { ApproveLaunchBanner } from './approve-launch-banner';
import { MessageList } from './message-list';
import { MessageInput } from './message-input';
import { useToastStore } from '../../stores/toast-store';

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
  /** If this conversation is linked to an autonomous run, pass the task ID */
  taskId?: string | null;
  /** Goal text for autonomous header display */
  autonomousGoal?: string | null;
  /** ISO timestamp when the autonomous run started */
  autonomousStartedAt?: string | null;
  /** Token budget for the autonomous run (null = unlimited) */
  autonomousTokenBudget?: number | null;
  /** Time budget in seconds (null = unlimited) */
  autonomousTimeBudget?: number | null;
  /** Current status of the background task */
  autonomousStatus?: 'running' | 'paused' | 'completed' | 'failed' | 'cancelled' | 'pending' | null;
  onClose?: () => void;
}

export function ConversationPanel({
  conversationId,
  taskId = null,
  autonomousGoal = null,
  autonomousStartedAt = null,
  autonomousTokenBudget = null,
  autonomousTimeBudget = null,
  autonomousStatus: initialAutonomousStatus = null,
  onClose,
}: ConversationPanelProps) {
  const queryClient = useQueryClient();

  // Autonomous run state
  const isAutonomous = taskId != null;
  const [autonomousStatus, setAutonomousStatus] = useState(initialAutonomousStatus);
  const [taskListCollapsed, setTaskListCollapsed] = useState(false);
  const [delegationTreeCollapsed, setDelegationTreeCollapsed] = useState(false);

  // Keep autonomous status in sync with prop changes
  useEffect(() => { setAutonomousStatus(initialAutonomousStatus); }, [initialAutonomousStatus]);

  // Fetch task list counts for the autonomous header
  const taskListQuery = $api.useQuery(
    'get',
    '/api/v1/background-tasks/{task_id}/task-list',
    { params: { path: { task_id: taskId! } } },
    { enabled: isAutonomous, refetchInterval: 5_000 },
  );

  const completedCount = taskListQuery.data?.completed_count ?? 0;
  const totalCount = taskListQuery.data?.total_count ?? 0;

  const isRunningAutonomous = isAutonomous && (autonomousStatus === 'running' || autonomousStatus === 'paused');
  const isPendingApproval = isAutonomous && autonomousStatus === 'pending';
  const showAutonomousHeader = isAutonomous && autonomousStatus != null && autonomousStatus !== 'pending';
  const showTaskListSidebar = isRunningAutonomous || (isAutonomous && autonomousStatus === 'completed');

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
      [conversationId, finalizeStreaming],
    ),
  );

  // Listen for background_update SSE events to track autonomous status changes
  useSSEEvent(
    useCallback(
      (event: SSEEvent) => {
        if (event.type === 'background_update' && taskId && event.task_id === taskId) {
          setAutonomousStatus(event.status as typeof autonomousStatus);
          // Refresh task list on status change
          queryClient.invalidateQueries({
            queryKey: ['get', '/api/v1/background-tasks/{task_id}/task-list'],
          });
        }
      },
      [taskId, queryClient],
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
        onError: () => {
          setIsStreaming(false);
          useToastStore.getState().addToast('Failed to send message. Please try again.', 'error');
        },
      },
    );
  };

  const handleApprovalRespond = async (requestId: string, approved: boolean) => {
    // TODO: This endpoint needs to be created on the backend.
    // The permission enforcer polls the DB for status changes on the PermissionRequest row,
    // so this PATCH just updates the row's status field.
    try {
      const response = await fetch(`/api/v1/agents/permission-requests/${requestId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: approved ? 'approved' : 'denied' }),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      // Remove from local state on success
      setApprovalRequests((prev) => prev.filter((r) => r.requestId !== requestId));
    } catch (err) {
      console.error('Failed to respond to approval request:', err);
      useToastStore.getState().addToast('Approval response failed. Please try again.', 'error');
    }
  };

  const handleLaunchApproved = (_conversationId: string, _taskId: string) => {
    setAutonomousStatus('running');
    // Refetch task list now that execution has started
    queryClient.invalidateQueries({
      queryKey: ['get', '/api/v1/background-tasks/{task_id}/task-list'],
    });
  };

  const inputDisabled = isStreaming || sendMessage.isPending;

  return (
    <div className="flex h-full bg-background">
      {/* Main conversation column */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header: autonomous or standard */}
        {showAutonomousHeader ? (
          <AutonomousHeader
            taskId={taskId!}
            goal={autonomousGoal ?? 'Autonomous run'}
            startedAt={autonomousStartedAt ?? new Date().toISOString()}
            tokenBudget={autonomousTokenBudget}
            timeBudget={autonomousTimeBudget}
            status={autonomousStatus!}
            completedCount={completedCount}
            totalCount={totalCount}
            onClose={onClose}
          />
        ) : (
          <ConversationHeader conversationId={conversationId} onClose={onClose} />
        )}

        {/* Message list */}
        <MessageList
          conversationId={conversationId}
          streamingContent={streamingContent}
          streamingToolCalls={streamingToolCalls}
          approvalRequests={approvalRequests}
          onApprovalRespond={handleApprovalRespond}
        />

        {/* Approve & Launch banner for pending autonomous runs */}
        {isPendingApproval && taskId && (
          <ApproveLaunchBanner
            taskId={taskId}
            onApproved={handleLaunchApproved}
          />
        )}

        {/* Message input */}
        <MessageInput
          conversationId={conversationId}
          disabled={inputDisabled}
          onSend={handleSend}
        />
      </div>

      {/* Task list sidebar for autonomous runs */}
      {showTaskListSidebar && taskId && (
        <TaskListSidebar
          taskId={taskId}
          collapsed={taskListCollapsed}
          onToggle={() => setTaskListCollapsed((prev) => !prev)}
        />
      )}

      {/* Delegation tree sidebar for autonomous runs with sub-agents */}
      {isAutonomous && taskId && (
        <DelegationTree
          taskId={taskId}
          collapsed={delegationTreeCollapsed}
          onToggle={() => setDelegationTreeCollapsed((prev) => !prev)}
        />
      )}
    </div>
  );
}
