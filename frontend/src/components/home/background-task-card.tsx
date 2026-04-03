import { useState, useRef, type KeyboardEvent } from 'react';
import { Card, CardBody, Badge, Button } from '../ui';
import { api } from '../../api/client';

export interface StepResult {
  step: number;
  summary: string;
  at: string;
}

export interface BackgroundTaskData {
  /** conversation_id from running session, used as key */
  conversation_id: string;
  agent_id: string;
  agent_name: string;
  status: string;
  started_at: string;
  last_activity: string;
  /** Populated from SSE background_progress events */
  task_id?: string;
  current_step?: number;
  total_steps?: number;
  step_label?: string;
  step_results?: StepResult[];
  completed?: boolean;
  /** Child tasks (sub-agents) */
  children?: BackgroundTaskData[];
}

type TaskStatus = 'running' | 'stale' | 'failed' | 'completed';

function inferStatus(task: BackgroundTaskData): TaskStatus {
  if (task.status === 'failed' || task.status === 'error') return 'failed';
  if (task.completed) return 'completed';

  // Stale: no activity in 5+ minutes
  const lastActivity = new Date(task.last_activity).getTime();
  const fiveMinutesAgo = Date.now() - 5 * 60_000;
  if (lastActivity < fiveMinutesAgo) return 'stale';

  return 'running';
}

const STATUS_DOT: Record<TaskStatus, string> = {
  running: 'bg-success',
  stale: 'bg-warning',
  failed: 'bg-destructive',
  completed: 'bg-primary',
};

function elapsedLabel(startedAt: string): string {
  const ms = Date.now() - new Date(startedAt).getTime();
  const secs = Math.floor(ms / 1_000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  return `${Math.floor(hrs / 24)}d`;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

interface BackgroundTaskCardProps {
  task: BackgroundTaskData;
  indented?: boolean;
}

export function BackgroundTaskCard({ task, indented = false }: BackgroundTaskCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [steerValue, setSteerValue] = useState('');
  const [steerLoading, setSteerLoading] = useState(false);
  const [steerError, setSteerError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const status = inferStatus(task);
  const dotColor = STATUS_DOT[status];
  const hasProgress = task.current_step != null && task.total_steps != null;
  const progressPct = hasProgress
    ? Math.min(100, Math.round((task.current_step! / task.total_steps!) * 100))
    : 0;

  const handleSteer = async () => {
    const trimmed = steerValue.trim();
    if (!trimmed || steerLoading) return;

    setSteerLoading(true);
    setSteerError(null);
    try {
      const res = await api.POST('/api/v1/conversations/{conversation_id}/steer', {
        params: { path: { conversation_id: task.conversation_id } },
        body: { message: trimmed },
      });
      if (res.error) {
        setSteerError('Failed to send steering message');
      } else {
        setSteerValue('');
      }
    } catch {
      setSteerError('Failed to send steering message');
    } finally {
      setSteerLoading(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSteer();
    }
  };

  return (
    <div className={indented ? 'ml-6' : ''}>
      <Card className="overflow-hidden">
        <CardBody className="py-2 px-3">
          {/* Compact row */}
          <button
            type="button"
            className="flex items-center gap-3 w-full text-left cursor-pointer"
            onClick={() => setExpanded((v) => !v)}
          >
            {/* Status dot */}
            <span className="relative flex h-2.5 w-2.5 shrink-0">
              {status === 'running' && (
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${dotColor} opacity-75`} />
              )}
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${dotColor}`} />
            </span>

            {/* Agent name + instruction */}
            <div className="flex flex-col min-w-0 flex-1">
              <span className="text-sm font-medium text-foreground truncate">
                {task.agent_name}
              </span>
              {task.step_label && (
                <span className="text-xs text-muted truncate">{task.step_label}</span>
              )}
            </div>

            {/* Progress bar */}
            {hasProgress && (
              <div className="flex items-center gap-2 shrink-0">
                <div className="w-20 h-1.5 bg-raised rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all duration-300"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <span className="text-xs text-muted tabular-nums whitespace-nowrap">
                  {task.current_step}/{task.total_steps}
                </span>
              </div>
            )}

            {/* Elapsed time */}
            <Badge variant="info" className="shrink-0">{elapsedLabel(task.started_at)}</Badge>

            {/* Expand toggle */}
            <span className="text-muted text-xs shrink-0 select-none">
              {expanded ? '\u25B2' : '\u25BC'}
            </span>
          </button>

          {/* Expanded view */}
          {expanded && (
            <div className="mt-3 pt-3 border-t border-border space-y-3">
              {/* Step history */}
              {task.step_results && task.step_results.length > 0 ? (
                <div className="space-y-1.5">
                  <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">Step History</h4>
                  <ol className="space-y-1">
                    {task.step_results.map((step, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs">
                        <span className="text-muted tabular-nums shrink-0 w-5 text-right">{step.step}.</span>
                        <span className="text-foreground flex-1">{step.summary}</span>
                        {step.at && (
                          <span className="text-muted shrink-0">{formatTimestamp(step.at)}</span>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              ) : (
                <p className="text-xs text-muted">No steps recorded yet.</p>
              )}

              {/* Steering input — only show for running/stale tasks */}
              {(status === 'running' || status === 'stale') && (
                <div className="space-y-1">
                  <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">Steer</h4>
                  <div className="flex items-center gap-2">
                    <input
                      ref={inputRef}
                      type="text"
                      value={steerValue}
                      onChange={(e) => setSteerValue(e.target.value)}
                      onKeyDown={handleKeyDown}
                      placeholder="Send a steering message..."
                      disabled={steerLoading}
                      className="flex-1 bg-raised text-foreground border border-border rounded-md px-3 py-1.5 text-xs placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-150"
                    />
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={handleSteer}
                      disabled={steerLoading || !steerValue.trim()}
                      loading={steerLoading}
                    >
                      Send
                    </Button>
                  </div>
                  {steerError && <p className="text-xs text-destructive">{steerError}</p>}
                </div>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Child tasks (sub-agents) */}
      {task.children && task.children.length > 0 && (
        <div className="mt-1 space-y-1">
          {task.children.map((child) => (
            <BackgroundTaskCard key={child.conversation_id} task={child} indented />
          ))}
        </div>
      )}
    </div>
  );
}
