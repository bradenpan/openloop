import { $api } from '../../api/hooks';
import type { components } from '../../api/types';
import { Card, CardHeader, CardBody } from '../ui';

type EmailMessage = components['schemas']['EmailMessageResponse'];

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

/** Extract the OL/ triage label prefix, or null for unlabelled messages. */
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

function MessageRow({ message }: { message: EmailMessage }) {
  const sender = message.from_name ?? message.from_address ?? 'Unknown';
  const subject = truncateSubject(message.subject, 40);
  const age = timeAgo(message.received_at);

  return (
    <a
      href={message.gmail_link ?? undefined}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 py-1.5 px-1 -mx-1 rounded hover:bg-raised/50 transition-colors duration-100 cursor-pointer group"
    >
      <span className="text-sm text-foreground shrink-0 max-w-[140px] truncate font-medium">
        {sender}
      </span>
      <span className="text-sm text-muted flex-1 min-w-0 truncate">
        {subject}
      </span>
      <span className="text-xs text-muted tabular-nums shrink-0">{age}</span>
    </a>
  );
}

function Skeleton() {
  return (
    <Card>
      <CardHeader className="py-2 px-3">
        <div className="h-3 w-16 rounded bg-raised animate-pulse" />
      </CardHeader>
      <CardBody className="py-1.5 px-3 space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3 py-1.5">
            <div className="h-3.5 w-24 rounded bg-raised animate-pulse" />
            <div className="h-3.5 w-40 rounded bg-raised animate-pulse" />
            <div className="h-3 w-6 rounded bg-raised animate-pulse" />
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

// Label display order — prioritised triage labels first
const LABEL_ORDER = ['Needs Response', 'Follow Up', 'FYI', 'Other'];

function sortLabels(labels: string[]): string[] {
  return [...labels].sort((a, b) => {
    const ai = LABEL_ORDER.indexOf(a);
    const bi = LABEL_ORDER.indexOf(b);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
}

export function EmailWidget() {
  const authStatus = $api.useQuery('get', '/api/v1/email/auth-status');
  const stats = $api.useQuery(
    'get',
    '/api/v1/email/stats',
    {},
    { enabled: authStatus.data?.authenticated === true },
  );
  const messages = $api.useQuery(
    'get',
    '/api/v1/email/messages',
    { params: { query: { limit: 20 } } },
    {
      enabled: authStatus.data?.authenticated === true,
      refetchInterval: 60_000,
    },
  );

  // Don't render if not connected
  if (authStatus.isLoading) return null;
  if (!authStatus.data?.authenticated) return null;

  if (messages.isLoading || stats.isLoading) return <Skeleton />;

  if (messages.isError || stats.isError) {
    return (
      <Card>
        <CardHeader className="py-2 px-3">
          <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">Email</h4>
        </CardHeader>
        <CardBody className="py-3 px-3">
          <p className="text-sm text-red-400">Failed to load email</p>
        </CardBody>
      </Card>
    );
  }

  const msgList = messages.data ?? [];
  const statsData = stats.data;
  const byLabel = (statsData?.by_label ?? {}) as Record<string, number>;
  const needsResponse = byLabel['OL/Needs Response'] ?? 0;

  const grouped = groupByTriageLabel(msgList);
  const labelKeys = sortLabels([...grouped.keys()]);

  return (
    <Card>
      <CardHeader className="py-2 px-3 flex items-center justify-between">
        <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">Email</h4>
      </CardHeader>
      <CardBody className="py-1.5 px-3">
        {/* Stats line */}
        <p className="text-sm text-muted mb-2">
          {statsData?.unread_count ?? 0} unread
          {needsResponse > 0 && <> &middot; {needsResponse} need response</>}
        </p>

        {msgList.length === 0 ? (
          <p className="text-sm text-muted py-2">No messages</p>
        ) : (
          <div className="space-y-3">
            {labelKeys.map((label) => {
              const group = grouped.get(label)!;
              return (
                <div key={label}>
                  <div className="text-[10px] font-semibold text-muted uppercase tracking-wider mb-1">
                    {label}
                  </div>
                  <div className="space-y-0.5">
                    {group.slice(0, 5).map((msg) => (
                      <MessageRow key={msg.id} message={msg} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Footer link */}
        <a
          href="https://mail.google.com"
          target="_blank"
          rel="noopener noreferrer"
          className="block text-xs text-primary hover:underline mt-3 pb-1"
        >
          View all in Gmail &rarr;
        </a>
      </CardBody>
    </Card>
  );
}
