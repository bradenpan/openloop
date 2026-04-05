import { Link } from 'react-router-dom';
import { $api } from '../../api/hooks';
import type { components } from '../../api/types';
import { Card, CardHeader, CardBody } from '../ui';
import type { WidgetProps } from './widget-registry';

type CalendarEvent = components['schemas']['CalendarEventResponse'];

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
}

function CompactEventRow({ event }: { event: CalendarEvent }) {
  const time = event.all_day
    ? 'All day'
    : formatTime(event.start_time);

  const dayLabel = (() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(event.start_time);
    target.setHours(0, 0, 0, 0);
    const diff = Math.round((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
    if (diff === 0) return '';
    if (diff === 1) return 'Tomorrow';
    return target.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  })();

  return (
    <a
      href={event.html_link ?? undefined}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-2 py-1 px-1 -mx-1 rounded hover:bg-raised/50 transition-colors duration-100 cursor-pointer"
    >
      <span className="text-xs text-muted tabular-nums shrink-0">
        {dayLabel ? `${dayLabel} ${time}` : time}
      </span>
      <span className="text-sm text-foreground flex-1 min-w-0 truncate">{event.title}</span>
    </a>
  );
}

export function CalendarEventsWidget(_props: WidgetProps) {
  const authStatus = $api.useQuery('get', '/api/v1/calendar/auth-status');

  const now = new Date();
  const end = new Date(now);
  end.setDate(end.getDate() + 14);

  const events = $api.useQuery(
    'get',
    '/api/v1/calendar/events',
    {
      params: {
        query: {
          start: now.toISOString(),
          end: end.toISOString(),
          limit: 5,
        },
      },
    },
    {
      enabled: authStatus.data?.authenticated === true,
      refetchInterval: 60_000,
    },
  );

  // Don't render if not connected
  if (!authStatus.data?.authenticated && !authStatus.isLoading) return null;

  const eventList = events.data ?? [];

  return (
    <Card>
      <CardHeader className="py-2 px-3 flex items-center justify-between">
        <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">
          Upcoming Events
        </h4>
        <Link to="/calendar" className="text-xs text-primary hover:underline">
          View all &rarr;
        </Link>
      </CardHeader>
      <CardBody className="py-1.5 px-3">
        {events.isError ? (
          <p className="text-sm text-muted py-2">Calendar unavailable</p>
        ) : events.isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-2 py-1">
                <div className="h-3 w-12 rounded bg-raised animate-pulse" />
                <div className="h-3 w-32 rounded bg-raised animate-pulse" />
              </div>
            ))}
          </div>
        ) : eventList.length === 0 ? (
          <p className="text-sm text-muted py-2">No upcoming events</p>
        ) : (
          <div className="space-y-0.5">
            {eventList.map((event) => (
              <CompactEventRow key={event.id} event={event} />
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
