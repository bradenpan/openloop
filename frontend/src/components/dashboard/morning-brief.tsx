import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Card, CardBody, Badge } from '../ui';
import { timeAgo } from '../../utils/dates';

// ---------------------------------------------------------------------------
// Status badge helper
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const variant = status === 'completed' ? 'success' : status === 'failed' ? 'danger' : 'info';
  return <Badge variant={variant}>{status}</Badge>;
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function ProgressBar({ completed, total }: { completed: number; total: number }) {
  if (total <= 0) return null;
  const pct = Math.min(100, Math.round((completed / total) * 100));
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-raised rounded-full overflow-hidden">
        <div
          className="h-full bg-primary rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-muted tabular-nums shrink-0">
        {completed}/{total}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsible summary text
// ---------------------------------------------------------------------------

function CollapsibleSummary({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const needsTruncation = text.length > 200;

  if (!needsTruncation) {
    return <p className="text-xs text-muted whitespace-pre-line">{text}</p>;
  }

  return (
    <div>
      <p className="text-xs text-muted whitespace-pre-line">
        {expanded ? text : text.slice(0, 200) + '...'}
      </p>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-primary hover:text-primary-hover transition-colors cursor-pointer mt-0.5"
      >
        {expanded ? 'Show less' : 'Show more'}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Duration formatter
// ---------------------------------------------------------------------------

function formatDuration(startedAt: string | null, completedAt: string | null): string | null {
  if (!startedAt || !completedAt) return null;
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (isNaN(ms) || ms < 0) return null;
  const totalMinutes = Math.floor(ms / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function MorningBrief() {
  const queryClient = useQueryClient();

  const brief = $api.useQuery('get', '/api/v1/home/morning-brief', undefined, {
    staleTime: 30_000,
  });

  const agents = brief.data?.agents ?? [];

  // Don't render when loading or empty
  if (brief.isLoading || agents.length === 0) {
    return null;
  }

  const dismissBrief = $api.useMutation('post', '/api/v1/home/morning-brief/dismiss', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/home/morning-brief'] });
    },
  });

  const handleDismiss = () => {
    dismissBrief.mutate({});
  };

  const totalRuns = agents.reduce((acc, a) => acc + a.runs.length, 0);
  const failedCount = brief.data?.failed_tasks_count ?? 0;
  const pendingApprovals = brief.data?.pending_approvals_count ?? 0;

  return (
    <section>
      <Card>
        {/* Header */}
        <div className="px-4 py-2.5 border-b border-border flex items-center gap-3">
          <h2 className="text-sm font-semibold text-foreground">
            Morning Brief
          </h2>
          <Badge variant="default">{totalRuns} run{totalRuns !== 1 ? 's' : ''}</Badge>
          {failedCount > 0 && (
            <Badge variant="danger">{failedCount} failed</Badge>
          )}
          {pendingApprovals > 0 && (
            <Badge variant="warning">{pendingApprovals} pending approval{pendingApprovals !== 1 ? 's' : ''}</Badge>
          )}
          <button
            onClick={handleDismiss}
            className="ml-auto px-2.5 py-1 text-xs font-medium rounded-md border border-border text-muted hover:text-foreground hover:bg-raised transition-colors cursor-pointer"
          >
            Dismiss
          </button>
        </div>

        {/* Agent groups */}
        <div className="divide-y divide-border">
          {agents.map((agent) => (
            <div key={agent.agent_id} className="px-4 py-3">
              {/* Agent name */}
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm font-medium text-foreground">{agent.agent_name}</span>
                <span className="text-xs text-muted">
                  {agent.runs.length} run{agent.runs.length !== 1 ? 's' : ''}
                </span>
              </div>

              {/* Runs */}
              <div className="space-y-2.5">
                {agent.runs.map((run) => {
                  const duration = formatDuration(run.started_at ?? null, run.completed_at ?? null);
                  return (
                    <div key={run.task_id} className="pl-3 border-l-2 border-border">
                      {/* Run header */}
                      <div className="flex items-center gap-2 flex-wrap">
                        <StatusBadge status={run.status} />
                        <span className="text-sm text-foreground truncate flex-1 min-w-0">
                          {run.goal
                            ? run.goal.length > 80
                              ? run.goal.slice(0, 80) + '...'
                              : run.goal
                            : 'Autonomous run'}
                        </span>
                        {duration && (
                          <span className="text-xs text-muted shrink-0 tabular-nums">{duration}</span>
                        )}
                        {run.completed_at && (
                          <span className="text-xs text-muted shrink-0 tabular-nums">
                            {timeAgo(run.completed_at)}
                          </span>
                        )}
                      </div>

                      {/* Progress */}
                      {run.total_count > 0 && (
                        <div className="mt-1 max-w-xs">
                          <ProgressBar completed={run.completed_count} total={run.total_count} />
                        </div>
                      )}

                      {/* Summary */}
                      {run.run_summary && (
                        <div className="mt-1.5">
                          <CollapsibleSummary text={run.run_summary} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </section>
  );
}
