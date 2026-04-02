import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button, Badge } from '../ui';
import type { components } from '../../api/types';

type MemoryResponse = components['schemas']['MemoryResponse'];
type ConsolidationReportResponse = components['schemas']['ConsolidationReportResponse'];

interface MemoryTabProps {
  spaceId: string;
}

type SubTab = 'facts' | 'rules';

// --- Stats bar ---

function StatsBar({ spaceId }: { spaceId: string }) {
  const { data: health } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}/memory/health',
    { params: { path: { space_id: spaceId } } },
  );

  if (!health) {
    return <div className="text-xs text-muted py-2">Loading stats...</div>;
  }

  const stats = [
    { label: 'Active Facts', value: health.active_facts, color: 'text-foreground' },
    { label: 'Archived', value: health.archived_facts, color: 'text-muted' },
    { label: 'Active Rules', value: health.active_rules, color: 'text-foreground' },
    { label: 'Inactive Rules', value: health.inactive_rules, color: 'text-muted' },
  ];

  return (
    <div className="grid grid-cols-4 gap-2 mb-4">
      {stats.map((stat) => (
        <div key={stat.label} className="bg-raised/50 border border-border rounded-md px-2 py-1.5 text-center">
          <div className={`text-base font-semibold ${stat.color}`}>{stat.value}</div>
          <div className="text-[10px] text-muted leading-tight">{stat.label}</div>
        </div>
      ))}
    </div>
  );
}

// --- Facts list ---

function FactsList({ spaceId }: { spaceId: string }) {
  const [showArchived, setShowArchived] = useState(false);
  const [pendingArchiveId, setPendingArchiveId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const namespace = `space:${spaceId}`;

  const { data: entries } = $api.useQuery(
    'get',
    '/api/v1/memory',
    { params: { query: { namespace, limit: 200 } } },
  );

  const archiveMutation = $api.useMutation('post', '/api/v1/memory/{entry_id}/archive', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/memory'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces/{space_id}/memory/health'] });
      setPendingArchiveId(null);
    },
  });

  const deleteMutation = $api.useMutation('delete', '/api/v1/memory/{entry_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/memory'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces/{space_id}/memory/health'] });
      setPendingDeleteId(null);
    },
  });

  const facts = entries ?? [];
  const filtered = showArchived ? facts : facts.filter((f: MemoryResponse) => !f.archived_at && (!f.valid_until || new Date(f.valid_until) > new Date()));

  function handleArchive(entryId: string) {
    archiveMutation.mutate({
      params: { path: { entry_id: entryId } },
      body: undefined as never,
    });
  }

  function handleDelete(entryId: string) {
    deleteMutation.mutate({
      params: { path: { entry_id: entryId } },
    });
  }

  function importanceBadge(importance: number) {
    if (importance >= 0.8) return <Badge>high</Badge>;
    if (importance >= 0.5) return <Badge>med</Badge>;
    return <Badge>low</Badge>;
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Toggle archived */}
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-muted">{filtered.length} fact{filtered.length !== 1 ? 's' : ''}</span>
        <label className="flex items-center gap-1.5 text-xs text-muted cursor-pointer">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="rounded"
          />
          Show archived
        </label>
      </div>

      {filtered.length === 0 && (
        <p className="text-sm text-muted text-center py-4">No facts in this space.</p>
      )}

      {filtered.map((fact: MemoryResponse) => (
        <div
          key={fact.id}
          className={`bg-raised/50 border border-border rounded-lg px-3 py-2 ${
            fact.archived_at || fact.valid_until ? 'opacity-50' : ''
          }`}
        >
          <div className="flex items-start gap-2">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="text-xs font-medium text-foreground truncate">{fact.key}</span>
                {importanceBadge(fact.importance)}
                {fact.category && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-primary/10 text-primary rounded">
                    {fact.category}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted leading-snug line-clamp-2">{fact.value}</p>
              <div className="flex items-center gap-2 mt-1 text-[10px] text-muted">
                <span>Accessed: {fact.access_count}x</span>
                {fact.archived_at && <span className="text-destructive">archived</span>}
                {fact.valid_until && !fact.archived_at && <span className="text-warning">superseded</span>}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-1 shrink-0">
              {!fact.archived_at && !fact.valid_until && (
                pendingArchiveId === fact.id ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleArchive(fact.id)}
                      disabled={archiveMutation.isPending}
                      className="text-[10px] text-destructive font-medium px-1.5 py-0.5 rounded bg-destructive/10 hover:bg-destructive/20 transition-colors cursor-pointer"
                    >
                      Archive?
                    </button>
                    <button
                      onClick={() => setPendingArchiveId(null)}
                      className="text-[10px] text-muted hover:text-foreground cursor-pointer"
                    >
                      No
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setPendingArchiveId(fact.id)}
                    className="text-muted hover:text-foreground p-0.5 rounded hover:bg-surface transition-colors cursor-pointer"
                    title="Archive"
                  >
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                      <path d="M2 4h8v6H2zM1 2h10v2H1zM5 6h2" />
                    </svg>
                  </button>
                )
              )}
              {pendingDeleteId === fact.id ? (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleDelete(fact.id)}
                    disabled={deleteMutation.isPending}
                    className="text-[10px] text-destructive font-medium px-1.5 py-0.5 rounded bg-destructive/10 hover:bg-destructive/20 transition-colors cursor-pointer"
                  >
                    Delete?
                  </button>
                  <button
                    onClick={() => setPendingDeleteId(null)}
                    className="text-[10px] text-muted hover:text-foreground cursor-pointer"
                  >
                    No
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setPendingDeleteId(fact.id)}
                  className="text-muted hover:text-destructive p-0.5 rounded hover:bg-destructive/10 transition-colors cursor-pointer"
                  title="Delete"
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                    <path d="M3 3l6 6M9 3l-6 6" />
                  </svg>
                </button>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// --- Rules list ---

function RulesList({ spaceId }: { spaceId: string }) {
  // Rules are agent-scoped; we show all rules from agents active in this space.
  // For now we show all rules via the behavioral-rules endpoints.
  // The memory health endpoint gives us counts but not individual rules.
  // We'll use the memory entries endpoint pattern — rules don't have a list-by-space endpoint,
  // so we display a message directing users to the agent's rules page.

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-muted">Behavioral rules for agents in this space</span>
      </div>

      <p className="text-sm text-muted text-center py-4">
        Behavioral rules are managed per-agent. Rule counts are shown in the stats bar above.
        Rules with very low confidence and high apply counts are automatically deactivated.
      </p>
    </div>
  );
}

// --- Consolidation report display ---

function ConsolidationReport({
  report,
  spaceId,
  onDone,
}: {
  report: ConsolidationReportResponse;
  spaceId: string;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [appliedMerges, setAppliedMerges] = useState<Set<number>>(new Set());
  const [appliedStale, setAppliedStale] = useState<Set<number>>(new Set());

  const applyMutation = $api.useMutation(
    'post',
    '/api/v1/spaces/{space_id}/memory/consolidate/apply',
    {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/memory'] });
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces/{space_id}/memory/health'] });
      },
    },
  );

  const totalItems = report.merges.length + report.contradictions.length + report.stale.length;

  if (totalItems === 0) {
    return (
      <div className="border border-border rounded-lg p-4 mt-3">
        <p className="text-sm text-muted text-center">Memory looks clean -- nothing to consolidate.</p>
        <div className="flex justify-center mt-3">
          <Button variant="secondary" size="sm" onClick={onDone}>
            Close
          </Button>
        </div>
      </div>
    );
  }

  function handleAcceptMerge(idx: number) {
    const merge = report.merges[idx];
    applyMutation.mutate({
      params: { path: { space_id: spaceId } },
      body: {
        merges: [{ source_ids: merge.source_ids, merged_value: merge.merged_value, reason: merge.reason }],
      },
    });
    setAppliedMerges((prev) => new Set(prev).add(idx));
  }

  function handleAcceptStale(idx: number) {
    const stale = report.stale[idx];
    applyMutation.mutate({
      params: { path: { space_id: spaceId } },
      body: {
        stale: [{ id: stale.id, reason: stale.reason }],
      },
    });
    setAppliedStale((prev) => new Set(prev).add(idx));
  }

  return (
    <div className="border border-border rounded-lg overflow-hidden mt-3">
      <div className="px-3 py-2 bg-raised/50 border-b border-border">
        <span className="text-xs font-medium text-foreground uppercase tracking-wider">
          Consolidation Report
        </span>
      </div>
      <div className="p-3 flex flex-col gap-3">
        {/* Merges */}
        {report.merges.length > 0 && (
          <div>
            <h4 className="text-xs font-medium text-foreground mb-1.5">Proposed Merges</h4>
            {report.merges.map((merge, idx) => (
              <div key={idx} className="bg-surface border border-border rounded-md p-2 mb-1.5">
                <p className="text-xs text-muted mb-1">
                  Merge {merge.source_ids.length} facts: {merge.reason || 'similar content'}
                </p>
                <p className="text-xs text-foreground mb-1.5 italic">"{merge.merged_value}"</p>
                <div className="flex gap-1.5">
                  <button
                    onClick={() => handleAcceptMerge(idx)}
                    disabled={appliedMerges.has(idx) || applyMutation.isPending}
                    className="text-[10px] font-medium px-2 py-0.5 rounded bg-primary/10 text-primary hover:bg-primary/20 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {appliedMerges.has(idx) ? 'Applied' : 'Accept'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Contradictions */}
        {report.contradictions.length > 0 && (
          <div>
            <h4 className="text-xs font-medium text-foreground mb-1.5">Contradictions Found</h4>
            {report.contradictions.map((c, idx) => (
              <div key={idx} className="bg-surface border border-border rounded-md p-2 mb-1.5">
                <p className="text-xs text-muted">
                  {c.description || `Entries ${c.ids.join(', ')} may contradict`}
                </p>
              </div>
            ))}
          </div>
        )}

        {/* Stale */}
        {report.stale.length > 0 && (
          <div>
            <h4 className="text-xs font-medium text-foreground mb-1.5">Stale Facts</h4>
            {report.stale.map((s, idx) => (
              <div key={idx} className="bg-surface border border-border rounded-md p-2 mb-1.5 flex items-center justify-between">
                <p className="text-xs text-muted flex-1">{s.reason || s.id}</p>
                <button
                  onClick={() => handleAcceptStale(idx)}
                  disabled={appliedStale.has(idx) || applyMutation.isPending}
                  className="text-[10px] font-medium px-2 py-0.5 rounded bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ml-2"
                >
                  {appliedStale.has(idx) ? 'Archived' : 'Archive'}
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end">
          <Button variant="secondary" size="sm" onClick={onDone}>
            Done
          </Button>
        </div>
      </div>
    </div>
  );
}

// --- Main Memory Tab ---

export function MemoryTab({ spaceId }: MemoryTabProps) {
  const [subTab, setSubTab] = useState<SubTab>('facts');
  const [consolidationReport, setConsolidationReport] = useState<ConsolidationReportResponse | null>(null);

  const consolidateMutation = $api.useMutation(
    'post',
    '/api/v1/spaces/{space_id}/memory/consolidate',
    {
      onSuccess: (data) => {
        setConsolidationReport(data);
      },
    },
  );

  function handleRunReview() {
    consolidateMutation.mutate({
      params: { path: { space_id: spaceId } },
      body: undefined as never,
    });
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Stats bar */}
      <StatsBar spaceId={spaceId} />

      {/* Sub-tab bar */}
      <div className="flex items-center gap-1 bg-raised rounded-md p-0.5 mb-1">
        <button
          onClick={() => setSubTab('facts')}
          className={`flex-1 px-3 py-1 text-xs font-medium rounded cursor-pointer transition-colors ${
            subTab === 'facts'
              ? 'bg-surface text-foreground shadow-sm'
              : 'text-muted hover:text-foreground'
          }`}
        >
          Facts
        </button>
        <button
          onClick={() => setSubTab('rules')}
          className={`flex-1 px-3 py-1 text-xs font-medium rounded cursor-pointer transition-colors ${
            subTab === 'rules'
              ? 'bg-surface text-foreground shadow-sm'
              : 'text-muted hover:text-foreground'
          }`}
        >
          Rules
        </button>
      </div>

      {/* Sub-tab content */}
      {subTab === 'facts' && <FactsList spaceId={spaceId} />}
      {subTab === 'rules' && <RulesList spaceId={spaceId} />}

      {/* Memory review action */}
      <div className="border-t border-border pt-3 mt-1">
        <Button
          variant="secondary"
          size="sm"
          onClick={handleRunReview}
          disabled={consolidateMutation.isPending}
          className="w-full"
        >
          {consolidateMutation.isPending ? 'Reviewing...' : 'Run Memory Review'}
        </Button>
        {consolidateMutation.isError && (
          <p className="text-xs text-destructive mt-1">
            Review failed. The LLM service may be unavailable.
          </p>
        )}
      </div>

      {/* Consolidation report */}
      {consolidationReport && (
        <ConsolidationReport
          report={consolidationReport}
          spaceId={spaceId}
          onDone={() => setConsolidationReport(null)}
        />
      )}
    </div>
  );
}
