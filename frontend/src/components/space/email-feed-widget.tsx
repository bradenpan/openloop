import { Link } from 'react-router-dom';
import { $api } from '../../api/hooks';
import type { components } from '../../api/types';
import { Card, CardHeader, CardBody } from '../ui';
import type { WidgetProps } from './widget-registry';

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

function CompactMessageRow({ message }: { message: EmailMessage }) {
  const sender = message.from_name ?? message.from_address ?? 'Unknown';
  const subject = truncateSubject(message.subject, 30);
  const age = timeAgo(message.received_at);

  return (
    <a
      href={message.gmail_link ?? undefined}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-2 py-1 px-1 -mx-1 rounded hover:bg-raised/50 transition-colors duration-100 cursor-pointer"
    >
      <span className="text-sm text-foreground shrink-0 max-w-[120px] truncate font-medium">
        {sender}
      </span>
      <span className="text-sm text-muted flex-1 min-w-0 truncate">
        {subject}
      </span>
      <span className="text-xs text-muted tabular-nums shrink-0">{age}</span>
    </a>
  );
}

export function EmailFeedWidget(_props: WidgetProps) {
  const authStatus = $api.useQuery('get', '/api/v1/email/auth-status');

  const messages = $api.useQuery(
    'get',
    '/api/v1/email/messages',
    { params: { query: { limit: 5 } } },
    {
      enabled: authStatus.data?.authenticated === true,
      refetchInterval: 60_000,
    },
  );

  // Don't render if not connected
  if (!authStatus.data?.authenticated && !authStatus.isLoading) return null;

  const msgList = messages.data ?? [];

  return (
    <Card>
      <CardHeader className="py-2 px-3 flex items-center justify-between">
        <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">
          Related Emails
        </h4>
        <Link to="/email" className="text-xs text-primary hover:underline">
          View all &rarr;
        </Link>
      </CardHeader>
      <CardBody className="py-1.5 px-3">
        {messages.isError ? (
          <p className="text-sm text-muted py-2">Email unavailable</p>
        ) : messages.isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-2 py-1">
                <div className="h-3 w-20 rounded bg-raised animate-pulse" />
                <div className="h-3 w-28 rounded bg-raised animate-pulse" />
                <div className="h-3 w-6 rounded bg-raised animate-pulse" />
              </div>
            ))}
          </div>
        ) : msgList.length === 0 ? (
          <p className="text-sm text-muted py-2">No recent emails</p>
        ) : (
          <div className="space-y-0.5">
            {msgList.map((msg) => (
              <CompactMessageRow key={msg.id} message={msg} />
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
