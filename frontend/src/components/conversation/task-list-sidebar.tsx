import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';

/** Shape of a single task item within the task_list array. */
interface TaskItem {
  label: string;
  status: 'completed' | 'in_progress' | 'pending' | 'skipped' | 'blocked';
}

interface TaskListSidebarProps {
  taskId: string;
  collapsed: boolean;
  onToggle: () => void;
}

/* ------------------------------------------------------------------ */
/*  Status icons                                                      */
/* ------------------------------------------------------------------ */

function StatusIcon({ status }: { status: TaskItem['status'] }) {
  switch (status) {
    case 'completed':
      return (
        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-success/15 text-success text-xs shrink-0">
          &#10003;
        </span>
      );
    case 'in_progress':
      return (
        <span className="flex items-center justify-center w-5 h-5 shrink-0">
          <span className="inline-block w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </span>
      );
    case 'pending':
      return (
        <span className="flex items-center justify-center w-5 h-5 shrink-0">
          <span className="w-3.5 h-3.5 rounded-full border-2 border-muted/40" />
        </span>
      );
    case 'skipped':
      return (
        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-muted/10 text-muted text-xs shrink-0">
          &#8594;
        </span>
      );
    case 'blocked':
      return (
        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-warning/15 text-warning text-xs shrink-0">
          &#9888;
        </span>
      );
  }
}

/* ------------------------------------------------------------------ */
/*  Collapsed rail                                                    */
/* ------------------------------------------------------------------ */

function CollapsedRail({ onToggle, completedCount, totalCount }: {
  onToggle: () => void;
  completedCount: number;
  totalCount: number;
}) {
  const pct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  return (
    <div className="flex flex-col items-center py-3 w-10 shrink-0 bg-surface border-l border-border">
      <button
        onClick={onToggle}
        className="text-muted hover:text-foreground transition-colors p-1.5 rounded-md hover:bg-raised cursor-pointer"
        aria-label="Expand task list"
        title="Task list"
      >
        {/* Checklist icon */}
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="2" y="2" width="12" height="12" rx="2" />
          <path d="M5 6l1.5 1.5L9 5" />
          <path d="M5 10h6" />
        </svg>
      </button>
      <span className="text-[10px] text-muted mt-1 [writing-mode:vertical-rl] rotate-180">
        {pct}%
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main sidebar                                                      */
/* ------------------------------------------------------------------ */

export function TaskListSidebar({ taskId, collapsed, onToggle }: TaskListSidebarProps) {
  const queryClient = useQueryClient();
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  // Fetch the task list — polls every 5s
  const { data } = $api.useQuery(
    'get',
    '/api/v1/background-tasks/{task_id}/task-list',
    { params: { path: { task_id: taskId } } },
    { refetchInterval: 5_000 },
  );

  // Also refetch on SSE background_progress events for this task
  useSSEEvent(
    useCallback(
      (event: SSEEvent) => {
        if (
          (event.type === 'background_progress' && event.task_id === taskId) ||
          (event.type === 'background_update' && event.task_id === taskId)
        ) {
          queryClient.invalidateQueries({
            queryKey: ['get', '/api/v1/background-tasks/{task_id}/task-list'],
          });
        }
      },
      [taskId, queryClient],
    ),
  );

  const rawList = (data?.task_list ?? []) as TaskItem[];
  const completedCount = data?.completed_count ?? 0;
  const totalCount = data?.total_count ?? rawList.length;
  const pct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  if (collapsed) {
    return (
      <CollapsedRail
        onToggle={onToggle}
        completedCount={completedCount}
        totalCount={totalCount}
      />
    );
  }

  return (
    <div className="flex flex-col w-[300px] min-w-[260px] max-w-[320px] shrink-0 bg-surface border-l border-border">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-sm font-semibold text-foreground truncate">Tasks</h3>
          <span className="text-xs text-muted whitespace-nowrap">
            {completedCount}/{totalCount}
          </span>
        </div>
        <button
          onClick={onToggle}
          className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised cursor-pointer shrink-0"
          aria-label="Collapse task list"
        >
          &#x2192;
        </button>
      </div>

      {/* Progress bar */}
      <div className="px-3 py-2 border-b border-border/50">
        <div className="flex items-center justify-between text-xs text-muted mb-1.5">
          <span>{completedCount} of {totalCount} complete</span>
          <span>{pct}%</span>
        </div>
        <div className="h-1.5 w-full bg-raised rounded-full overflow-hidden">
          <div
            className="h-full bg-primary rounded-full transition-all duration-500 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto">
        {rawList.length === 0 && (
          <div className="px-3 py-6 text-center">
            <p className="text-xs text-muted">No tasks yet.</p>
            <p className="text-[11px] text-muted/60 mt-1">Tasks will appear as the agent plans its work.</p>
          </div>
        )}

        {rawList.map((item, idx) => (
          <div
            key={idx}
            className={`flex items-start gap-2.5 px-3 py-2 transition-colors ${
              hoveredIdx === idx ? 'bg-raised/50' : ''
            } ${item.status === 'in_progress' ? 'bg-primary/5' : ''}`}
            onMouseEnter={() => setHoveredIdx(idx)}
            onMouseLeave={() => setHoveredIdx(null)}
          >
            <div className="mt-0.5">
              <StatusIcon status={item.status} />
            </div>
            <span
              className={`text-sm leading-snug ${
                item.status === 'completed'
                  ? 'text-muted line-through'
                  : item.status === 'skipped'
                    ? 'text-muted/60'
                    : item.status === 'blocked'
                      ? 'text-warning'
                      : item.status === 'in_progress'
                        ? 'text-foreground font-medium'
                        : 'text-foreground'
              }`}
            >
              {item.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
