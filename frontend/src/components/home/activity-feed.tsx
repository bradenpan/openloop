import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import type { components } from '../../api/types';
import { useSSEEvent, type SSEEvent } from '../../hooks/use-sse';
import { Card, CardBody } from '../ui';
import { timeAgo } from '../../utils/dates';

type AuditEntry = components['schemas']['AuditLogResponse'];
type Agent = components['schemas']['AgentResponse'];

// ---------------------------------------------------------------------------
// Time range options
// ---------------------------------------------------------------------------

type TimeRange = '1h' | '24h' | '7d';

function getAfterDate(range: TimeRange): string {
  const now = new Date();
  switch (range) {
    case '1h':
      return new Date(now.getTime() - 60 * 60 * 1_000).toISOString();
    case '24h':
      return new Date(now.getTime() - 24 * 60 * 60 * 1_000).toISOString();
    case '7d':
      return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1_000).toISOString();
  }
}

// ---------------------------------------------------------------------------
// Format an audit entry as human-readable text
// ---------------------------------------------------------------------------

function formatEntry(entry: AuditEntry, agentName: string): string {
  const action = entry.action || entry.tool_name;
  const summary = entry.input_summary;

  // Try to build a readable sentence
  if (summary) {
    return `${agentName} ${action} -- ${summary}`;
  }
  return `${agentName} ${action}`;
}

// ---------------------------------------------------------------------------
// Activity Feed component
// ---------------------------------------------------------------------------

export function ActivityFeed() {
  const queryClient = useQueryClient();
  const lastRefetchRef = useRef(0);

  const [timeRange, setTimeRange] = useState<TimeRange>('24h');
  const [agentFilter, setAgentFilter] = useState<string>('');
  const [displayLimit, setDisplayLimit] = useState(20);

  // Stable "after" date — only recompute when timeRange changes
  const [afterDate, setAfterDate] = useState(() => getAfterDate(timeRange));
  useEffect(() => {
    setAfterDate(getAfterDate(timeRange));
  }, [timeRange]);

  // Fetch agents for name lookup and filter dropdown
  const agents = $api.useQuery('get', '/api/v1/agents');

  // Fetch audit log with filters
  const auditLog = $api.useQuery('get', '/api/v1/audit-log', {
    params: {
      query: {
        agent_id: agentFilter || undefined,
        after: afterDate,
        limit: 50,
        offset: 0,
      },
    },
  }, {
    refetchInterval: 10_000, // Poll every 10 seconds
    staleTime: 8_000,
  });

  // Listen for SSE events for real-time updates
  const handleSSE = useCallback((event: SSEEvent) => {
    if (
      event.type === 'background_progress' ||
      event.type === 'autonomous_progress' ||
      event.type === 'background_update'
    ) {
      const now = Date.now();
      if (now - lastRefetchRef.current > 3_000) {
        lastRefetchRef.current = now;
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/audit-log'] });
      }
    }
  }, [queryClient]);

  useSSEEvent(handleSSE);

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

  // Get unique agent list for dropdown
  const agentOptions = useMemo(() => {
    return agents.data?.map((a) => ({ id: a.id, name: a.name })) ?? [];
  }, [agents.data]);

  const entries = auditLog.data ?? [];
  const visibleEntries = entries.slice(0, displayLimit);
  const hasMore = entries.length > displayLimit;

  const isLoading = auditLog.isLoading || agents.isLoading;

  if (isLoading) {
    return (
      <Card>
        <CardBody className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3 py-1.5">
              <div className="h-3 w-3 rounded-full bg-raised animate-pulse" />
              <div className="h-3 w-48 rounded bg-raised animate-pulse" />
              <div className="ml-auto h-3 w-12 rounded bg-raised animate-pulse" />
            </div>
          ))}
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      {/* Filter bar */}
      <div className="px-4 py-2 border-b border-border flex items-center gap-3 flex-wrap">
        {/* Agent filter */}
        <select
          value={agentFilter}
          onChange={(e) => {
            setAgentFilter(e.target.value);
            setDisplayLimit(20);
          }}
          className="text-xs bg-surface border border-border rounded-md px-2 py-1 text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="">All agents</option>
          {agentOptions.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>

        {/* Time range toggles */}
        <div className="flex items-center gap-0.5 bg-raised rounded-md p-0.5">
          {(['1h', '24h', '7d'] as const).map((range) => (
            <button
              key={range}
              onClick={() => {
                setTimeRange(range);
                setDisplayLimit(20);
              }}
              className={`px-2 py-0.5 text-xs rounded transition-colors cursor-pointer ${
                timeRange === range
                  ? 'bg-surface text-foreground font-medium shadow-sm'
                  : 'text-muted hover:text-foreground'
              }`}
            >
              {range}
            </button>
          ))}
        </div>

        {/* Entry count */}
        <span className="text-xs text-muted ml-auto">
          {entries.length} event{entries.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Entries list */}
      <CardBody className="p-0">
        {visibleEntries.length === 0 ? (
          <p className="text-sm text-muted py-6 text-center">No recent activity.</p>
        ) : (
          <div className="divide-y divide-border">
            {visibleEntries.map((entry) => (
              <div
                key={entry.id}
                className="flex items-center gap-3 px-4 py-2 text-sm"
              >
                {/* Action indicator dot */}
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary/40 shrink-0" />

                {/* Entry text */}
                <span className="text-foreground truncate flex-1 text-xs">
                  {formatEntry(entry, agentMap.get(entry.agent_id) ?? 'Unknown Agent')}
                </span>

                {/* Timestamp */}
                <span className="text-xs text-muted shrink-0 tabular-nums">
                  {timeAgo(entry.timestamp)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Show more */}
        {hasMore && (
          <div className="px-4 py-2 border-t border-border">
            <button
              onClick={() => setDisplayLimit((l) => l + 20)}
              className="text-xs text-primary hover:text-primary-hover transition-colors cursor-pointer"
            >
              Show more ({entries.length - displayLimit} remaining)
            </button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
