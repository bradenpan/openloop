import { useCallback, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { api } from '../../api/client';
import type { components } from '../../api/types';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { useToastStore } from '../../stores/toast-store';
import { Card, CardBody, Badge } from '../ui';
import { timeAgo } from '../../utils/dates';

type ApprovalEntry = components['schemas']['ApprovalQueueResponse'];

// ---------------------------------------------------------------------------
// Readable action type labels
// ---------------------------------------------------------------------------

function readableActionType(actionType: string): string {
  // Convert snake_case/kebab-case to human readable
  return actionType
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Single approval row
// ---------------------------------------------------------------------------

interface ApprovalRowProps {
  entry: ApprovalEntry;
  agentName: string;
  onResolved: () => void;
}

function ApprovalRow({ entry, agentName, onResolved }: ApprovalRowProps) {
  const addToast = useToastStore((s) => s.addToast);
  const [loading, setLoading] = useState<'approve' | 'deny' | null>(null);

  const handleResolve = async (status: 'approved' | 'denied') => {
    setLoading(status === 'approved' ? 'approve' : 'deny');
    try {
      const res = await api.POST('/api/v1/approval-queue/{approval_id}/resolve', {
        params: { path: { approval_id: entry.id } },
        body: { status, resolved_by: 'user' },
      });
      if (res.error) {
        addToast(`Failed to ${status === 'approved' ? 'approve' : 'deny'}.`, 'error');
      } else {
        addToast(
          status === 'approved' ? 'Approved.' : 'Denied.',
          status === 'approved' ? 'success' : 'warning',
        );
        onResolved();
      }
    } catch {
      addToast('Failed to resolve approval.', 'error');
    } finally {
      setLoading(null);
    }
  };

  const actionDescription = entry.action_detail
    ? JSON.stringify(entry.action_detail).slice(0, 100)
    : readableActionType(entry.action_type);

  return (
    <div className="flex items-start gap-3 px-4 py-3">
      {/* Warning indicator */}
      <span className="inline-block w-2 h-2 rounded-full bg-warning mt-1.5 shrink-0" />

      {/* Content */}
      <div className="flex flex-col min-w-0 flex-1 gap-0.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">{agentName}</span>
          <span className="text-xs text-muted">wants to</span>
          <span className="text-sm text-foreground">{readableActionType(entry.action_type)}</span>
        </div>
        {entry.reason && (
          <p className="text-xs text-muted truncate">{entry.reason}</p>
        )}
        {entry.action_detail && Object.keys(entry.action_detail).length > 0 && (
          <p className="text-xs text-muted truncate" title={actionDescription}>
            {actionDescription}
          </p>
        )}
      </div>

      {/* Timestamp */}
      <span className="text-xs text-muted shrink-0 tabular-nums mt-0.5">
        {timeAgo(entry.created_at)}
      </span>

      {/* Approve / Deny buttons */}
      <div className="flex items-center gap-1.5 shrink-0">
        <button
          onClick={() => handleResolve('approved')}
          disabled={loading !== null}
          className="px-2.5 py-1 text-xs font-medium rounded-md border border-success text-success hover:bg-success/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading === 'approve' ? '...' : 'Approve'}
        </button>
        <button
          onClick={() => handleResolve('denied')}
          disabled={loading !== null}
          className="px-2.5 py-1 text-xs font-medium rounded-md border border-destructive text-destructive hover:bg-destructive/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading === 'deny' ? '...' : 'Deny'}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function PendingApprovals() {
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const lastRefetchRef = useRef(0);
  const [batchLoading, setBatchLoading] = useState<'approve' | 'deny' | null>(null);

  // Fetch pending approvals
  const approvals = $api.useQuery('get', '/api/v1/approval-queue', {
    params: { query: { limit: 50, offset: 0 } },
  }, {
    refetchInterval: 10_000,
    staleTime: 8_000,
  });

  // Fetch agents for name lookup
  const agents = $api.useQuery('get', '/api/v1/agents');

  // Listen for approval_queued SSE events
  const handleSSE = useCallback((event: SSEEvent) => {
    if (event.type === 'approval_queued') {
      const now = Date.now();
      if (now - lastRefetchRef.current > 1_000) {
        lastRefetchRef.current = now;
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/approval-queue'] });
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/home/dashboard'] });
      }
    }
  }, [queryClient]);

  useSSEEvent(handleSSE);

  const agentMap = useMemo(() => {
    const map = new Map<string, string>();
    if (agents.data) {
      for (const agent of agents.data) {
        map.set(agent.id, agent.name);
      }
    }
    return map;
  }, [agents.data]);

  const handleResolved = () => {
    queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/approval-queue'] });
    queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/home/dashboard'] });
  };

  const handleBatchResolve = async (status: 'approved' | 'denied') => {
    const entries = approvals.data ?? [];
    if (entries.length === 0) return;

    setBatchLoading(status === 'approved' ? 'approve' : 'deny');
    try {
      const res = await api.POST('/api/v1/approval-queue/batch-resolve', {
        body: {
          approval_ids: entries.map((e) => e.id),
          status,
          resolved_by: 'user',
        },
      });
      if (res.error) {
        addToast(`Failed to ${status === 'approved' ? 'approve' : 'deny'} all.`, 'error');
      } else {
        addToast(
          `${status === 'approved' ? 'Approved' : 'Denied'} ${entries.length} item${entries.length !== 1 ? 's' : ''}.`,
          status === 'approved' ? 'success' : 'warning',
        );
        handleResolved();
      }
    } catch {
      addToast('Batch resolve failed.', 'error');
    } finally {
      setBatchLoading(null);
    }
  };

  const entries = approvals.data ?? [];
  const isLoading = approvals.isLoading || agents.isLoading;

  // Hidden entirely when empty (not loading)
  if (!isLoading && entries.length === 0) {
    return null;
  }

  if (isLoading) {
    // Don't show skeleton for approvals — it's hidden when empty anyway
    return null;
  }

  return (
    <section>
      <Card>
        {/* Section header with badge count and batch actions */}
        <div className="px-4 py-2.5 border-b border-border flex items-center gap-3">
          <h2 className="text-sm font-semibold text-foreground">
            Pending Approvals
          </h2>
          <Badge variant="warning">{entries.length}</Badge>

          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => handleBatchResolve('approved')}
              disabled={batchLoading !== null}
              className="px-2 py-0.5 text-xs font-medium rounded-md border border-success text-success hover:bg-success/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {batchLoading === 'approve' ? '...' : 'Approve All'}
            </button>
            <button
              onClick={() => handleBatchResolve('denied')}
              disabled={batchLoading !== null}
              className="px-2 py-0.5 text-xs font-medium rounded-md border border-destructive text-destructive hover:bg-destructive/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {batchLoading === 'deny' ? '...' : 'Deny All'}
            </button>
          </div>
        </div>

        {/* Approval entries */}
        <div className="divide-y divide-border">
          {entries.map((entry) => (
            <ApprovalRow
              key={entry.id}
              entry={entry}
              agentName={agentMap.get(entry.agent_id) ?? 'Unknown Agent'}
              onResolved={handleResolved}
            />
          ))}
        </div>
      </Card>
    </section>
  );
}
