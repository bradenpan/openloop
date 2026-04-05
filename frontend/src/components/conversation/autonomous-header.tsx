import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { Button } from '../ui';

type RunStatus = 'running' | 'paused' | 'completed' | 'failed' | 'cancelled' | 'pending';

interface AutonomousHeaderProps {
  taskId: string;
  goal: string;
  /** ISO timestamp when the run started */
  startedAt: string;
  /** Token budget (null = unlimited) */
  tokenBudget: number | null;
  /** Time budget in seconds (null = unlimited) */
  timeBudget: number | null;
  /** Current task status */
  status: RunStatus;
  /** Completed / total from task list */
  completedCount: number;
  totalCount: number;
  onClose?: () => void;
}

/* ------------------------------------------------------------------ */
/*  Elapsed time hook                                                 */
/* ------------------------------------------------------------------ */

function useElapsed(startedAt: string, running: boolean): string {
  const [, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    if (running) {
      intervalRef.current = setInterval(() => setTick((t) => t + 1), 1_000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [running]);

  const ms = Date.now() - new Date(startedAt).getTime();
  if (isNaN(ms) || ms < 0) return '0s';
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  if (mins < 60) return `${mins}m ${remSecs}s`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `${hrs}h ${remMins}m`;
}

/* ------------------------------------------------------------------ */
/*  Status badge                                                      */
/* ------------------------------------------------------------------ */

function StatusBadge({ status }: { status: RunStatus }) {
  const config: Record<RunStatus, { label: string; className: string }> = {
    running: { label: 'Running', className: 'bg-primary/15 text-primary' },
    paused: { label: 'Paused', className: 'bg-warning/15 text-warning' },
    completed: { label: 'Complete', className: 'bg-success/15 text-success' },
    failed: { label: 'Failed', className: 'bg-destructive/15 text-destructive' },
    cancelled: { label: 'Cancelled', className: 'bg-muted/15 text-muted' },
    pending: { label: 'Pending', className: 'bg-muted/15 text-muted' },
  };

  const c = config[status] ?? config.running;

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${c.className}`}>
      {status === 'running' && (
        <span className="w-1.5 h-1.5 rounded-full bg-primary mr-1.5 animate-pulse" />
      )}
      {c.label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Budget display                                                    */
/* ------------------------------------------------------------------ */

function BudgetInfo({ tokenBudget, timeBudget, startedAt }: {
  tokenBudget: number | null;
  timeBudget: number | null;
  startedAt: string;
}) {
  const parts: string[] = [];

  if (tokenBudget != null) {
    parts.push(`${(tokenBudget / 1000).toFixed(0)}k tokens`);
  }

  if (timeBudget != null) {
    const elapsed = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000);
    const remaining = Math.max(0, timeBudget - elapsed);
    const mins = Math.floor(remaining / 60);
    const hrs = Math.floor(mins / 60);
    if (hrs > 0) {
      parts.push(`${hrs}h ${mins % 60}m left`);
    } else {
      parts.push(`${mins}m left`);
    }
  }

  if (parts.length === 0) return null;

  return (
    <span className="text-[11px] text-muted whitespace-nowrap">
      {parts.join(' / ')}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Main header component                                             */
/* ------------------------------------------------------------------ */

export function AutonomousHeader({
  taskId,
  goal,
  startedAt,
  tokenBudget,
  timeBudget,
  status: initialStatus,
  completedCount: initialCompleted,
  totalCount: initialTotal,
  onClose,
}: AutonomousHeaderProps) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<RunStatus>(initialStatus);
  const [completedCount, setCompletedCount] = useState(initialCompleted);
  const [totalCount, setTotalCount] = useState(initialTotal);

  // Keep in sync with prop changes
  useEffect(() => { setStatus(initialStatus); }, [initialStatus]);
  useEffect(() => { setCompletedCount(initialCompleted); }, [initialCompleted]);
  useEffect(() => { setTotalCount(initialTotal); }, [initialTotal]);

  const isRunning = status === 'running';
  const isPaused = status === 'paused';
  const isFinished = status === 'completed' || status === 'failed' || status === 'cancelled';

  const elapsed = useElapsed(startedAt, isRunning);
  const pct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  // Pause / resume mutations
  const pauseMutation = $api.useMutation('post', '/api/v1/background-tasks/{task_id}/pause');
  const resumeMutation = $api.useMutation('post', '/api/v1/background-tasks/{task_id}/resume');

  const handlePause = () => {
    pauseMutation.mutate(
      { params: { path: { task_id: taskId } } },
      {
        onSuccess: () => {
          setStatus('paused');
          queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/background-tasks/{task_id}/task-list'] });
        },
      },
    );
  };

  const handleResume = () => {
    resumeMutation.mutate(
      { params: { path: { task_id: taskId } } },
      {
        onSuccess: () => {
          setStatus('running');
          queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/background-tasks/{task_id}/task-list'] });
        },
      },
    );
  };

  // Listen for SSE updates for this task
  useSSEEvent(
    useCallback(
      (event: SSEEvent) => {
        if (event.type === 'background_update' && event.task_id === taskId) {
          const newStatus = event.status as RunStatus;
          setStatus(newStatus);
        }
        if (event.type === 'background_progress' && event.task_id === taskId) {
          // Refresh task list counts
          queryClient.invalidateQueries({
            queryKey: ['get', '/api/v1/background-tasks/{task_id}/task-list'],
          });
        }
      },
      [taskId, queryClient],
    ),
  );

  // Progress bar color
  const barColor = isFinished
    ? status === 'completed'
      ? 'bg-success'
      : 'bg-destructive'
    : isPaused
      ? 'bg-warning'
      : 'bg-primary';

  return (
    <div className="shrink-0 border-b border-border bg-surface">
      {/* Top row: goal + controls */}
      <div className="flex items-center gap-3 px-4 py-2">
        {/* Goal text */}
        <div className="flex-1 min-w-0 flex items-center gap-2">
          <StatusBadge status={status} />
          <span
            className="text-sm font-medium text-foreground truncate"
            title={goal}
          >
            {goal}
          </span>
        </div>

        {/* Elapsed time */}
        <span className="text-xs text-muted whitespace-nowrap tabular-nums">
          {elapsed}
        </span>

        {/* Budget info */}
        <BudgetInfo tokenBudget={tokenBudget} timeBudget={timeBudget} startedAt={startedAt} />

        {/* Progress count */}
        {totalCount > 0 && (
          <span className="text-xs text-muted whitespace-nowrap">
            {completedCount}/{totalCount}
          </span>
        )}

        {/* Controls */}
        <div className="flex items-center gap-1.5 shrink-0">
          {isRunning && (
            <Button
              size="sm"
              variant="secondary"
              onClick={handlePause}
              loading={pauseMutation.isPending}
              title="Pause at next turn boundary"
            >
              &#9646;&#9646;
            </Button>
          )}
          {isPaused && (
            <Button
              size="sm"
              variant="primary"
              onClick={handleResume}
              loading={resumeMutation.isPending}
              title="Resume execution"
            >
              &#9654;
            </Button>
          )}
          {onClose && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onClose}
              title="Close"
            >
              &#x2715;
            </Button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1 w-full bg-raised">
        <div
          className={`h-full ${barColor} transition-all duration-700 ease-out`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
