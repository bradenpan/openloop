import { useCallback, useRef } from 'react';
import { $api } from '../../api/hooks';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { useQueryClient } from '@tanstack/react-query';
import { BackgroundTaskCard, type BackgroundTaskData, type StepResult } from './background-task-card';
import { Card, CardBody } from '../ui';

// In-memory store for SSE progress data keyed by conversation_id.
// We use a module-level Map so data persists across re-renders without
// needing a Zustand store for this narrow use case.
const progressCache = new Map<string, {
  task_id?: string;
  current_step?: number;
  total_steps?: number;
  step_label?: string;
  step_results: StepResult[];
  completed?: boolean;
}>();

function Skeleton() {
  return (
    <div className="space-y-2">
      {[1, 2].map((i) => (
        <Card key={i}>
          <CardBody className="flex items-center gap-3 py-2.5">
            <div className="h-2 w-2 rounded-full bg-raised animate-pulse" />
            <div className="h-4 w-32 rounded bg-raised animate-pulse" />
            <div className="ml-auto h-4 w-12 rounded bg-raised animate-pulse" />
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

export function BackgroundTaskPanel() {
  const queryClient = useQueryClient();
  const lastRefetchRef = useRef(0);

  // Poll running sessions every 5 seconds
  const running = $api.useQuery('get', '/api/v1/agents/running', {}, {
    refetchInterval: 5_000,
  });

  // Fetch agents for name lookup
  const agents = $api.useQuery('get', '/api/v1/agents');

  // Also fetch conversations to get any active conversations not in "running" list
  const conversations = $api.useQuery('get', '/api/v1/conversations');

  // Listen for SSE background_progress events to populate step data
  const handleSSE = useCallback((event: SSEEvent) => {
    if (event.type === 'background_progress') {
      const { conversation_id, task_id, turn, completed, summary } = event;

      const existing = progressCache.get(conversation_id) ?? {
        step_results: [],
      };

      // Build updated step result
      const stepResult: StepResult = {
        step: turn,
        summary,
        at: new Date().toISOString(),
      };

      // Only add if this turn isn't already recorded
      const alreadyRecorded = existing.step_results.some((s) => s.step === turn);
      const updatedResults = alreadyRecorded ? existing.step_results : [...existing.step_results, stepResult];

      progressCache.set(conversation_id, {
        task_id,
        current_step: turn,
        total_steps: completed ? turn : Math.max(turn + 1, existing.total_steps ?? turn + 1),
        step_label: `Step ${turn}${completed ? '' : `/${existing.total_steps ?? '?'}`}: ${summary.slice(0, 100)}`,
        step_results: updatedResults,
        completed,
      });

      // Throttle query invalidation to once per second max
      const now = Date.now();
      if (now - lastRefetchRef.current > 1_000) {
        lastRefetchRef.current = now;
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents/running'] });
      }
    }

    if (event.type === 'background_update') {
      // Status change — refetch running list
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents/running'] });
    }
  }, [queryClient]);

  useSSEEvent(handleSSE);

  const isLoading = running.isLoading || agents.isLoading || conversations.isLoading;
  if (isLoading) return <Skeleton />;

  // Build agent name lookup
  const agentMap = new Map<string, string>();
  if (agents.data) {
    for (const agent of agents.data) {
      agentMap.set(agent.id, agent.name);
    }
  }

  // Build tasks from running sessions
  const runningSessions = (running.data ?? []) as Array<{
    conversation_id: string;
    agent_id: string;
    space_id: string | null;
    sdk_session_id: string | null;
    status: string;
    started_at: string;
    last_activity: string;
  }>;

  // Also include active conversations that aren't in the running list
  // (for sessions that have conversation status=active but may not be in the in-memory tracker)
  const runningConvIds = new Set(runningSessions.map((s) => s.conversation_id));
  const activeConversations = (conversations.data ?? []).filter(
    (c) => c.status === 'active' && !runningConvIds.has(c.id)
  );

  const tasks: BackgroundTaskData[] = runningSessions.map((session) => {
    const cached = progressCache.get(session.conversation_id);
    return {
      conversation_id: session.conversation_id,
      agent_id: session.agent_id,
      agent_name: agentMap.get(session.agent_id) ?? 'Unknown Agent',
      status: session.status,
      started_at: session.started_at,
      last_activity: session.last_activity,
      task_id: cached?.task_id,
      current_step: cached?.current_step,
      total_steps: cached?.total_steps,
      step_label: cached?.step_label,
      step_results: cached?.step_results,
      completed: cached?.completed,
    };
  });

  // Add active conversations that aren't in running sessions
  for (const conv of activeConversations) {
    const cached = progressCache.get(conv.id);
    tasks.push({
      conversation_id: conv.id,
      agent_id: conv.agent_id,
      agent_name: agentMap.get(conv.agent_id) ?? 'Unknown Agent',
      status: 'active',
      started_at: conv.created_at,
      last_activity: conv.updated_at ?? conv.created_at,
      task_id: cached?.task_id,
      current_step: cached?.current_step,
      total_steps: cached?.total_steps,
      step_label: cached?.step_label,
      step_results: cached?.step_results,
      completed: cached?.completed,
    });
  }

  if (tasks.length === 0) {
    return (
      <p className="text-sm text-muted py-2">No active agent sessions.</p>
    );
  }

  // For now, all tasks are top-level (parent-child grouping would require
  // backend background_task data which we don't have an endpoint for).
  // When the backend exposes parent_task_id through the running endpoint,
  // we can group them here.

  return (
    <div className="space-y-1.5">
      {tasks.map((task) => (
        <BackgroundTaskCard key={task.conversation_id} task={task} />
      ))}
    </div>
  );
}
