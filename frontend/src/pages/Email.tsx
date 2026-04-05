import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../api/hooks';
import type { components } from '../api/types';
import { Card, CardBody, Badge, Button } from '../components/ui';

type EmailMessage = components['schemas']['EmailMessageResponse'];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function timeAgo(date: string): string {
  const now = Date.now();
  const then = new Date(date).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 60) return `${Math.max(1, diffMin)}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d`;
}

function truncateSubject(subject: string | null, max: number): string {
  if (!subject) return '(no subject)';
  if (subject.length <= max) return subject;
  return subject.slice(0, max) + '\u2026';
}

function getTriageLabel(msg: EmailMessage): string | null {
  if (!msg.labels || !Array.isArray(msg.labels)) return null;
  for (const l of msg.labels) {
    const label = typeof l === 'string' ? l : (l as { name?: string })?.name;
    if (label && label.startsWith('OL/')) return label.replace('OL/', '');
  }
  return null;
}

function groupByTriageLabel(messages: EmailMessage[]): Map<string, EmailMessage[]> {
  const groups = new Map<string, EmailMessage[]>();
  for (const msg of messages) {
    const label = getTriageLabel(msg) ?? 'Other';
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label)!.push(msg);
  }
  return groups;
}

const LABEL_ORDER = ['Needs Response', 'Follow Up', 'FYI', 'Other'];

function sortLabels(labels: string[]): string[] {
  return [...labels].sort((a, b) => {
    const ai = LABEL_ORDER.indexOf(a);
    const bi = LABEL_ORDER.indexOf(b);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
}

function labelVariant(label: string): 'default' | 'primary' | 'success' | 'danger' | 'warning' {
  if (label === 'Needs Response') return 'warning';
  if (label === 'Follow Up') return 'primary';
  if (label === 'FYI') return 'default';
  return 'default';
}

// ─── Icons ──────────────────────────────────────────────────────────────────

function SyncIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={spinning ? 'animate-spin' : ''}
    >
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
    </svg>
  );
}

function ArchiveIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="21 8 21 21 3 21 3 8" />
      <rect x="1" y="3" width="22" height="5" />
      <line x1="10" y1="12" x2="14" y2="12" />
    </svg>
  );
}

function MarkReadIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="text-muted"
    >
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

// ─── Message row ────────────────────────────────────────────────────────────

function MessageRow({
  message,
  onArchive,
  onMarkRead,
}: {
  message: EmailMessage;
  onArchive: (id: string) => void;
  onMarkRead: (id: string) => void;
}) {
  const sender = message.from_name ?? message.from_address ?? 'Unknown';
  const subject = truncateSubject(message.subject, 60);
  const age = timeAgo(message.received_at);
  const triageLabel = getTriageLabel(message);

  return (
    <div className="flex items-center gap-3 py-2.5 px-3 border-b border-border last:border-b-0 group hover:bg-raised/50 transition-colors duration-100">
      {/* Unread indicator */}
      {message.is_unread && (
        <span className="w-2 h-2 rounded-full bg-primary shrink-0" />
      )}
      {!message.is_unread && <span className="w-2 shrink-0" />}

      {/* Sender */}
      <span className={`text-sm shrink-0 max-w-[160px] truncate ${message.is_unread ? 'font-semibold text-foreground' : 'text-foreground'}`}>
        {sender}
      </span>

      {/* Subject + snippet */}
      <a
        href={message.gmail_link ?? undefined}
        target="_blank"
        rel="noopener noreferrer"
        className="flex-1 min-w-0 truncate cursor-pointer"
      >
        <span className={`text-sm ${message.is_unread ? 'font-medium text-foreground' : 'text-foreground'}`}>
          {subject}
        </span>
        {message.snippet && (
          <span className="text-sm text-muted ml-1.5">
            &mdash; {message.snippet.slice(0, 60)}
          </span>
        )}
      </a>

      {/* Label badge */}
      {triageLabel && (
        <Badge variant={labelVariant(triageLabel)} className="shrink-0 text-[10px]">
          {triageLabel}
        </Badge>
      )}

      {/* Time */}
      <span className="text-xs text-muted tabular-nums shrink-0">{age}</span>

      {/* Quick actions */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
        {message.is_unread && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onMarkRead(message.gmail_message_id ?? message.id); }}
            className="p-1 rounded text-muted hover:text-foreground hover:bg-raised transition-colors cursor-pointer"
            title="Mark read"
          >
            <MarkReadIcon />
          </button>
        )}
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onArchive(message.gmail_message_id ?? message.id); }}
          className="p-1 rounded text-muted hover:text-foreground hover:bg-raised transition-colors cursor-pointer"
          title="Archive"
        >
          <ArchiveIcon />
        </button>
      </div>
    </div>
  );
}

// ─── Loading skeleton ────────────────────────────────────────────────────────

function PageSkeleton() {
  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <div className="h-6 w-32 rounded bg-raised animate-pulse" />
        <div className="h-9 w-24 rounded bg-raised animate-pulse" />
      </div>
      <div className="h-5 w-64 rounded bg-raised animate-pulse" />
      <div className="h-9 w-full rounded bg-raised animate-pulse" />
      {[1, 2].map((g) => (
        <div key={g} className="space-y-2">
          <div className="h-4 w-28 rounded bg-raised animate-pulse" />
          <Card>
            <CardBody className="space-y-3 py-2 px-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-3 py-1.5">
                  <div className="h-3.5 w-24 rounded bg-raised animate-pulse" />
                  <div className="h-3.5 w-48 rounded bg-raised animate-pulse" />
                  <div className="h-3 w-8 rounded bg-raised animate-pulse" />
                </div>
              ))}
            </CardBody>
          </Card>
        </div>
      ))}
    </div>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function Email() {
  const queryClient = useQueryClient();
  const [syncError, setSyncError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [limit, setLimit] = useState(50);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());

  const authStatus = $api.useQuery('get', '/api/v1/email/auth-status');

  const stats = $api.useQuery(
    'get',
    '/api/v1/email/stats',
    {},
    {
      enabled: authStatus.data?.authenticated === true,
      refetchInterval: 60_000,
    },
  );

  const messages = $api.useQuery(
    'get',
    '/api/v1/email/messages',
    {
      params: {
        query: {
          limit,
          ...(searchQuery ? { query: searchQuery } : {}),
        },
      },
    },
    {
      enabled: authStatus.data?.authenticated === true,
      refetchInterval: 60_000,
    },
  );

  const syncMutation = $api.useMutation('post', '/api/v1/email/sync', {
    onSuccess: () => {
      setSyncError(null);
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/email/messages'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/email/stats'] });
    },
    onError: () => {
      setSyncError('Sync failed \u2014 try again');
    },
  });

  const archiveMutation = $api.useMutation('post', '/api/v1/email/messages/{message_id}/archive', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/email/messages'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/email/stats'] });
    },
  });

  const markReadMutation = $api.useMutation('post', '/api/v1/email/messages/{message_id}/read', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/email/messages'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/email/stats'] });
    },
  });

  function handleArchive(messageId: string) {
    archiveMutation.mutate({ params: { path: { message_id: messageId } } });
  }

  function handleMarkRead(messageId: string) {
    markReadMutation.mutate({ params: { path: { message_id: messageId } } });
  }

  function toggleSection(label: string) {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }

  if (authStatus.isLoading || messages.isLoading) return <PageSkeleton />;

  if (!authStatus.data?.authenticated) {
    return (
      <div className="max-w-3xl">
        <h1 className="text-xl font-bold text-foreground mb-4">Email</h1>
        <Card>
          <CardBody className="py-8 text-center">
            <p className="text-sm text-muted">
              Gmail is not connected. Go to Settings to connect your account.
            </p>
          </CardBody>
        </Card>
      </div>
    );
  }

  if (messages.isError) {
    return (
      <div className="space-y-6 max-w-3xl">
        <h1 className="text-xl font-bold text-foreground">Email</h1>
        <Card>
          <CardBody className="py-8 text-center">
            <p className="text-sm text-red-400">Failed to load email messages</p>
          </CardBody>
        </Card>
      </div>
    );
  }

  const msgList = messages.data ?? [];
  const grouped = groupByTriageLabel(msgList);
  const labelKeys = sortLabels([...grouped.keys()]);

  const statsData = stats.data;
  const byLabel = (statsData?.by_label ?? {}) as Record<string, number>;
  const needsResponse = byLabel['Needs Response'] ?? byLabel['OL/Needs Response'] ?? 0;
  const followUp = byLabel['Follow Up'] ?? byLabel['OL/Follow Up'] ?? 0;

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-foreground">Email</h1>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => { setSyncError(null); syncMutation.mutate({}); }}
          disabled={syncMutation.isPending}
        >
          <SyncIcon spinning={syncMutation.isPending} />
          <span className="ml-1.5">{syncMutation.isPending ? 'Syncing...' : 'Sync now'}</span>
        </Button>
      </div>

      {/* Sync error feedback */}
      {syncError && (
        <p className="text-xs text-red-500">{syncError}</p>
      )}

      {/* Sync result feedback */}
      {syncMutation.isSuccess && syncMutation.data && (
        <p className="text-xs text-muted">
          Synced: {syncMutation.data.added} added, {syncMutation.data.updated} updated
        </p>
      )}

      {/* Stats bar */}
      {statsData && (
        <p className="text-sm text-muted">
          {statsData.unread_count} unread
          {needsResponse > 0 && <> &middot; {needsResponse} need response</>}
          {followUp > 0 && <> &middot; {followUp} follow up</>}
        </p>
      )}

      {/* Search bar */}
      <div className="relative">
        <div className="absolute left-3 top-1/2 -translate-y-1/2">
          <SearchIcon />
        </div>
        <input
          type="text"
          placeholder="Search messages..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full pl-9 pr-3 py-2 text-sm bg-surface border border-border rounded-md text-foreground placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Message list grouped by label */}
      {msgList.length === 0 ? (
        <Card>
          <CardBody className="py-8 text-center">
            <p className="text-sm text-muted">
              {searchQuery ? 'No messages match your search.' : 'No messages.'}
            </p>
          </CardBody>
        </Card>
      ) : (
        labelKeys.map((label) => {
          const group = grouped.get(label)!;
          const isCollapsed = collapsedSections.has(label);

          return (
            <section key={label}>
              <button
                type="button"
                onClick={() => toggleSection(label)}
                className="flex items-center gap-2 mb-2 cursor-pointer group"
              >
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className={`text-muted shrink-0 transition-transform duration-150 ${isCollapsed ? '-rotate-90' : ''}`}
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
                <h2 className="text-sm font-semibold text-muted uppercase tracking-wide">
                  {label}
                </h2>
                <span className="text-xs text-muted">({group.length})</span>
              </button>
              {!isCollapsed && (
                <Card>
                  <CardBody className="p-0">
                    {group.map((msg) => (
                      <MessageRow
                        key={msg.id}
                        message={msg}
                        onArchive={handleArchive}
                        onMarkRead={handleMarkRead}
                      />
                    ))}
                  </CardBody>
                </Card>
              )}
            </section>
          );
        })
      )}

      {/* Load more */}
      {msgList.length >= limit && (
        <div className="text-center">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setLimit((prev) => prev + 50)}
          >
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
