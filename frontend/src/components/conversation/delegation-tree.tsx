import { useCallback, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { api } from '../../api/client';
import type { components } from '../../api/types';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { useToastStore } from '../../stores/toast-store';
import { Badge } from '../ui';

type RunningSession = components['schemas']['RunningSessionResponse'];

/* ------------------------------------------------------------------ */
/*  Status helpers                                                     */
/* ------------------------------------------------------------------ */

type NodeStatus = 'running' | 'active' | 'background' | 'completed' | 'done' | 'failed' | 'cancelled' | 'paused' | 'pending' | 'queued' | 'interrupted';

const statusConfig: Record<NodeStatus, { label: string; dotClass: string; badgeVariant: 'default' | 'success' | 'warning' | 'danger' | 'info' }> = {
  running: { label: 'Running', dotClass: 'bg-success', badgeVariant: 'success' },
  active: { label: 'Running', dotClass: 'bg-success', badgeVariant: 'success' },
  background: { label: 'Running', dotClass: 'bg-success', badgeVariant: 'success' },
  completed: { label: 'Complete', dotClass: 'bg-primary', badgeVariant: 'default' },
  done: { label: 'Complete', dotClass: 'bg-primary', badgeVariant: 'default' },
  failed: { label: 'Failed', dotClass: 'bg-destructive', badgeVariant: 'danger' },
  cancelled: { label: 'Cancelled', dotClass: 'bg-muted', badgeVariant: 'info' },
  paused: { label: 'Paused', dotClass: 'bg-warning', badgeVariant: 'warning' },
  pending: { label: 'Pending', dotClass: 'bg-muted', badgeVariant: 'info' },
  queued: { label: 'Queued', dotClass: 'bg-muted', badgeVariant: 'info' },
  interrupted: { label: 'Interrupted', dotClass: 'bg-warning', badgeVariant: 'warning' },
};

function getStatusConfig(status: string) {
  return statusConfig[status as NodeStatus] ?? statusConfig.running;
}

/* ------------------------------------------------------------------ */
/*  Tree node type                                                     */
/* ------------------------------------------------------------------ */

interface TreeNode {
  session: RunningSession;
  agentName: string;
  children: TreeNode[];
}

/* ------------------------------------------------------------------ */
/*  Single tree node                                                   */
/* ------------------------------------------------------------------ */

function DelegationNode({ node, depth }: { node: TreeNode; depth: number }) {
  const [expanded, setExpanded] = useState(false);
  const [pauseLoading, setPauseLoading] = useState(false);
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const session = node.session;
  const cfg = getStatusConfig(session.status);
  const delegationDepth = session.delegation_depth ?? 0;
  const isRunning = session.status === 'active' || session.status === 'background' || session.status === 'running';
  const isPaused = session.status === 'paused';
  const canPause = (isRunning || isPaused) && session.background_task_id;

  const instruction = session.instruction;
  const truncated = instruction
    ? instruction.length > 60
      ? instruction.slice(0, 60) + '...'
      : instruction
    : null;

  const handlePause = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!session.background_task_id || pauseLoading) return;
    setPauseLoading(true);
    try {
      const endpoint = isPaused
        ? '/api/v1/background-tasks/{task_id}/resume' as const
        : '/api/v1/background-tasks/{task_id}/pause' as const;
      const res = await api.POST(endpoint, {
        params: { path: { task_id: session.background_task_id } },
      });
      if (res.error) {
        addToast(`Failed to ${isPaused ? 'resume' : 'pause'} task.`, 'error');
      } else {
        addToast(`Task ${isPaused ? 'resumed' : 'paused'}.`, 'success');
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents/running'] });
      }
    } catch {
      addToast(`Failed to ${isPaused ? 'resume' : 'pause'} task.`, 'error');
    } finally {
      setPauseLoading(false);
    }
  };

  return (
    <div className={depth > 0 ? 'ml-4 border-l border-border/50 pl-3' : ''}>
      <div className="py-1.5">
        {/* Main row */}
        <button
          type="button"
          className="flex items-center gap-2 w-full text-left cursor-pointer group"
          onClick={() => setExpanded((v) => !v)}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${node.agentName}`}
        >
          {/* Status dot */}
          <span className="relative flex h-2 w-2 shrink-0">
            {isRunning && (
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${cfg.dotClass} opacity-75`} />
            )}
            <span className={`relative inline-flex rounded-full h-2 w-2 ${cfg.dotClass}`} />
          </span>

          {/* Agent name + instruction */}
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-xs font-medium text-foreground truncate">
              {node.agentName}
            </span>
            {truncated && (
              <span className="text-[11px] text-muted truncate">{truncated}</span>
            )}
          </div>

          {/* Delegation depth badge */}
          <Badge variant="info" className="shrink-0 text-[10px] px-1.5 py-0">
            D{delegationDepth}
          </Badge>

          {/* Status badge */}
          <Badge variant={cfg.badgeVariant} className="shrink-0 text-[10px] px-1.5 py-0">
            {cfg.label}
          </Badge>

          {/* Pause/Resume button */}
          {canPause && (
            <button
              onClick={handlePause}
              disabled={pauseLoading}
              className="inline-flex items-center justify-center w-5 h-5 rounded-md text-muted hover:text-warning hover:bg-warning/10 transition-colors cursor-pointer disabled:opacity-50 shrink-0"
              title={isPaused ? 'Resume' : 'Pause'}
              aria-label={isPaused ? 'Resume sub-agent' : 'Pause sub-agent'}
            >
              {isPaused ? (
                <svg width="8" height="10" viewBox="0 0 8 10" fill="currentColor">
                  <polygon points="0,0 8,5 0,10" />
                </svg>
              ) : (
                <svg width="8" height="10" viewBox="0 0 8 10" fill="none">
                  <rect x="0" y="0" width="3" height="10" rx="0.5" fill="currentColor" />
                  <rect x="5" y="0" width="3" height="10" rx="0.5" fill="currentColor" />
                </svg>
              )}
            </button>
          )}

          {/* Expand toggle */}
          <span className="text-muted text-[10px] shrink-0 select-none group-hover:text-foreground transition-colors">
            {expanded ? '\u25B2' : '\u25BC'}
          </span>
        </button>

        {/* Expanded: progress + children summary */}
        {expanded && (
          <div className="mt-1.5 ml-4 text-[11px] text-muted space-y-1">
            {session.completed_count != null && session.total_count != null && session.total_count > 0 && (
              <div className="flex items-center gap-2">
                <span>Progress: {session.completed_count}/{session.total_count}</span>
                <div className="w-16 h-1 bg-raised rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all duration-300"
                    style={{ width: `${Math.min(100, Math.round((session.completed_count / session.total_count) * 100))}%` }}
                  />
                </div>
              </div>
            )}
            {node.children.length > 0 && (
              <span>{node.children.length} sub-agent{node.children.length !== 1 ? 's' : ''}</span>
            )}
          </div>
        )}
      </div>

      {/* Child nodes */}
      {node.children.length > 0 && (
        <div className="space-y-0.5">
          {node.children.map((child) => (
            <DelegationNode
              key={child.session.background_task_id ?? child.session.conversation_id}
              node={child}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main delegation tree                                               */
/* ------------------------------------------------------------------ */

interface DelegationTreeProps {
  taskId: string;
  collapsed: boolean;
  onToggle: () => void;
}

export function DelegationTree({ taskId, collapsed, onToggle }: DelegationTreeProps) {
  const queryClient = useQueryClient();
  const lastRefetchRef = useRef(0);

  // Fetch all running sessions
  const running = $api.useQuery('get', '/api/v1/agents/running', {}, {
    refetchInterval: 5_000,
  });

  // Fetch agents for name lookup
  const agents = $api.useQuery('get', '/api/v1/agents');

  // Listen for SSE events to trigger real-time updates
  useSSEEvent(
    useCallback(
      (event: SSEEvent) => {
        if (
          event.type === 'background_progress' ||
          event.type === 'background_update' ||
          event.type === 'goal_complete'
        ) {
          const now = Date.now();
          if (now - lastRefetchRef.current > 1_000) {
            lastRefetchRef.current = now;
            queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents/running'] });
          }
        }
      },
      [queryClient],
    ),
  );

  // Build agent name lookup
  const agentMap = useMemo(() => {
    const map = new Map<string, string>();
    if (agents.data) {
      for (const agent of agents.data) {
        map.set(agent.id, agent.name);
      }
    }
    return map;
  }, [agents.data]);

  // Build the tree: find children of this taskId
  const childNodes = useMemo(() => {
    const sessions = running.data ?? [];

    // Find all sessions that are children of this task
    const childSessions = sessions.filter(
      (s) => s.parent_task_id === taskId,
    );

    if (childSessions.length === 0) return [];

    // Build a map of background_task_id → session for recursive nesting
    const byTaskId = new Map<string, RunningSession>();
    for (const s of sessions) {
      if (s.background_task_id) {
        byTaskId.set(s.background_task_id, s);
      }
    }

    // Recursive tree builder
    function buildNode(session: RunningSession): TreeNode {
      const children = sessions
        .filter((s) => s.parent_task_id === session.background_task_id)
        .map(buildNode);

      return {
        session,
        agentName: agentMap.get(session.agent_id) ?? 'Sub-agent',
        children,
      };
    }

    return childSessions.map(buildNode);
  }, [running.data, taskId, agentMap]);

  // Don't render if no children
  if (childNodes.length === 0) return null;

  const totalChildren = childNodes.reduce(
    function countAll(acc: number, node: TreeNode): number {
      return node.children.reduce(countAll, acc + 1);
    },
    0,
  );
  const runningCount = childNodes.reduce(
    function countRunning(acc: number, node: TreeNode): number {
      const isRunning = node.session.status === 'active' || node.session.status === 'background' || node.session.status === 'running';
      return node.children.reduce(countRunning, acc + (isRunning ? 1 : 0));
    },
    0,
  );

  if (collapsed) {
    return (
      <div className="flex flex-col items-center py-3 w-10 shrink-0 bg-surface border-l border-border">
        <button
          onClick={onToggle}
          className="text-muted hover:text-foreground transition-colors p-1.5 rounded-md hover:bg-raised cursor-pointer"
          aria-label="Expand delegation tree"
          title="Delegation tree"
        >
          {/* Tree icon */}
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="8" cy="3" r="2" />
            <circle cx="4" cy="12" r="2" />
            <circle cx="12" cy="12" r="2" />
            <line x1="8" y1="5" x2="4" y2="10" />
            <line x1="8" y1="5" x2="12" y2="10" />
          </svg>
        </button>
        <span className="text-[10px] text-muted mt-1 [writing-mode:vertical-rl] rotate-180">
          {totalChildren}
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col w-[280px] min-w-[240px] max-w-[300px] shrink-0 bg-surface border-l border-border">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-sm font-semibold text-foreground truncate">Sub-agents</h3>
          <span className="text-xs text-muted whitespace-nowrap">
            {runningCount}/{totalChildren} running
          </span>
        </div>
        <button
          onClick={onToggle}
          className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised cursor-pointer shrink-0"
          aria-label="Collapse delegation tree"
        >
          &#x2192;
        </button>
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {childNodes.map((node) => (
          <DelegationNode
            key={node.session.background_task_id ?? node.session.conversation_id}
            node={node}
            depth={0}
          />
        ))}
      </div>
    </div>
  );
}
