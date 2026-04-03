import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { api } from '../../api/client';
import type { components } from '../../api/types';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { useToastStore } from '../../stores/toast-store';
import { Card, CardBody, Badge } from '../ui';

type RunningSession = components['schemas']['RunningSessionResponse'];

// ---------------------------------------------------------------------------
// Run type badge colors — muted pills
// ---------------------------------------------------------------------------

const runTypeBadge: Record<string, { variant: 'default' | 'success' | 'warning' | 'danger' | 'info'; label: string }> = {
  interactive: { variant: 'info', label: 'Interactive' },
  autonomous: { variant: 'default', label: 'Autonomous' },
  heartbeat: { variant: 'success', label: 'Heartbeat' },
  task: { variant: 'info', label: 'Task' },
  automation: { variant: 'warning', label: 'Automation' },
};

// ---------------------------------------------------------------------------
// Elapsed time — live-updating
// ---------------------------------------------------------------------------

function ElapsedTime({ startedAt }: { startedAt: string }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1_000);
    return () => clearInterval(interval);
  }, []);

  const ms = Date.now() - new Date(startedAt).getTime();
  const secs = Math.floor(ms / 1_000);
  if (secs < 60) return <>{secs}s</>;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return <>{mins}m {secs % 60}s</>;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return <>{hrs}h {mins % 60}m</>;
  return <>{Math.floor(hrs / 24)}d {hrs % 24}h</>;
}

// ---------------------------------------------------------------------------
// Single agent row
// ---------------------------------------------------------------------------

interface AgentRowProps {
  session: RunningSession;
  agentName: string;
}

function AgentRow({ session, agentName }: AgentRowProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [pauseLoading, setPauseLoading] = useState(false);
  const [stopLoading, setStopLoading] = useState(false);

  const runType = session.run_type ?? 'interactive';
  const badge = runTypeBadge[runType] ?? runTypeBadge.interactive;
  const hasProgress = session.completed_count != null && session.total_count != null && session.total_count > 0;
  const progressPct = hasProgress
    ? Math.min(100, Math.round(((session.completed_count ?? 0) / (session.total_count ?? 1)) * 100))
    : 0;

  const instruction = session.instruction;
  const truncatedInstruction = instruction
    ? instruction.length > 80
      ? instruction.slice(0, 80) + '...'
      : instruction
    : null;

  const handlePause = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!session.background_task_id || pauseLoading) return;
    setPauseLoading(true);
    try {
      const res = await api.POST('/api/v1/background-tasks/{task_id}/pause', {
        params: { path: { task_id: session.background_task_id } },
      });
      if (res.error) {
        addToast('Failed to pause task.', 'error');
      } else {
        addToast('Task paused.', 'success');
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents/running'] });
      }
    } catch {
      addToast('Failed to pause task.', 'error');
    } finally {
      setPauseLoading(false);
    }
  };

  const handleStop = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!session.background_task_id || stopLoading) return;
    setStopLoading(true);
    try {
      const res = await api.POST('/api/v1/background-tasks/{task_id}/pause', {
        params: { path: { task_id: session.background_task_id } },
      });
      if (res.error) {
        addToast('Failed to stop task.', 'error');
      } else {
        addToast('Task stopped.', 'warning');
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents/running'] });
      }
    } catch {
      addToast('Failed to stop task.', 'error');
    } finally {
      setStopLoading(false);
    }
  };

  const handleRowClick = () => {
    if (session.conversation_id && session.space_id) {
      navigate(`/space/${session.space_id}`);
    }
  };

  return (
    <Card className="hover:border-primary/30 transition-colors duration-150">
      <CardBody className="py-2 px-3">
        <div
          className="flex items-center gap-3 cursor-pointer"
          onClick={handleRowClick}
        >
          {/* Status dot */}
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-success" />
          </span>

          {/* Agent name + task description */}
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-sm font-medium text-foreground truncate">
              {agentName}
            </span>
            {truncatedInstruction && (
              <span className="text-xs text-muted truncate">{truncatedInstruction}</span>
            )}
          </div>

          {/* Progress bar (autonomous only) */}
          {hasProgress && (
            <div className="flex items-center gap-2 shrink-0">
              <div className="w-20 h-1 bg-raised rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all duration-500"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <span className="text-xs text-muted tabular-nums whitespace-nowrap">
                {session.completed_count}/{session.total_count}
              </span>
            </div>
          )}

          {/* Run type badge */}
          <Badge variant={badge.variant} className="shrink-0 text-[10px] px-2 py-0">
            {badge.label}
          </Badge>

          {/* Elapsed time */}
          <span className="text-xs text-muted tabular-nums shrink-0 min-w-[3rem] text-right">
            <ElapsedTime startedAt={session.started_at} />
          </span>

          {/* Token budget indicator */}
          {session.token_budget != null && (
            <span className="text-[10px] text-muted shrink-0" title="Token budget">
              {formatTokenBudget(session.token_budget)}
            </span>
          )}

          {/* Inline controls */}
          <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
            {/* Pause button — for autonomous/automation runs with a background task */}
            {session.background_task_id && (runType === 'autonomous' || runType === 'automation') && (
              <button
                onClick={handlePause}
                disabled={pauseLoading}
                className="inline-flex items-center justify-center w-6 h-6 rounded-md text-muted hover:text-warning hover:bg-warning/10 transition-colors cursor-pointer disabled:opacity-50"
                title="Pause"
                aria-label="Pause task"
              >
                <svg width="10" height="12" viewBox="0 0 10 12" fill="none">
                  <rect x="1" y="1" width="3" height="10" rx="0.5" fill="currentColor" />
                  <rect x="6" y="1" width="3" height="10" rx="0.5" fill="currentColor" />
                </svg>
              </button>
            )}

            {/* System-wide stop is available via the kill switch in the header */}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

function formatTokenBudget(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M tok`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k tok`;
  return `${n} tok`;
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function ActiveAgents() {
  const queryClient = useQueryClient();
  const lastRefetchRef = useRef(0);

  // Poll running sessions every 5 seconds
  const running = $api.useQuery('get', '/api/v1/agents/running', {}, {
    refetchInterval: 5_000,
  });

  // Fetch agents for name lookup
  const agents = $api.useQuery('get', '/api/v1/agents');

  // Listen for SSE events to trigger real-time updates
  const handleSSE = useCallback((event: SSEEvent) => {
    if (
      event.type === 'autonomous_progress' ||
      event.type === 'background_update' ||
      event.type === 'background_progress' ||
      event.type === 'goal_complete'
    ) {
      // Throttle query invalidation to once per second max
      const now = Date.now();
      if (now - lastRefetchRef.current > 1_000) {
        lastRefetchRef.current = now;
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents/running'] });
      }
    }
  }, [queryClient]);

  useSSEEvent(handleSSE);

  const isLoading = running.isLoading || agents.isLoading;

  if (isLoading) {
    return (
      <div className="space-y-1.5">
        {[1, 2].map((i) => (
          <Card key={i}>
            <CardBody className="flex items-center gap-3 py-2.5 px-3">
              <div className="h-2 w-2 rounded-full bg-raised animate-pulse" />
              <div className="h-4 w-32 rounded bg-raised animate-pulse" />
              <div className="ml-auto h-4 w-12 rounded bg-raised animate-pulse" />
            </CardBody>
          </Card>
        ))}
      </div>
    );
  }

  // Build agent name lookup
  const agentMap = new Map<string, string>();
  if (agents.data) {
    for (const agent of agents.data) {
      agentMap.set(agent.id, agent.name);
    }
  }

  const sessions = running.data ?? [];

  if (sessions.length === 0) {
    return (
      <p className="text-sm text-muted py-2">No active agents.</p>
    );
  }

  return (
    <div className="space-y-1.5">
      {sessions.map((session) => (
        <AgentRow
          key={session.conversation_id || session.background_task_id || session.agent_id}
          session={session}
          agentName={agentMap.get(session.agent_id) ?? 'Unknown Agent'}
        />
      ))}
    </div>
  );
}

/** Hook returning true if there are active running agents (for conditional ordering). */
export function useHasActiveAgents(): boolean {
  const running = $api.useQuery('get', '/api/v1/agents/running', {}, {
    refetchInterval: 5_000,
  });
  return (running.data?.length ?? 0) > 0;
}
