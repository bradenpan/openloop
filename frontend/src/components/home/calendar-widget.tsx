import { $api } from '../../api/hooks';
import type { components } from '../../api/types';
import { Card, CardHeader, CardBody } from '../ui';

type CalendarEvent = components['schemas']['CalendarEventResponse'];

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
}

function getDayLabel(date: Date): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  const diff = Math.round((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  return target.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
}

function groupByDay(events: CalendarEvent[]): Map<string, CalendarEvent[]> {
  const groups = new Map<string, CalendarEvent[]>();
  for (const event of events) {
    const label = getDayLabel(new Date(event.start_time));
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label)!.push(event);
  }
  return groups;
}

function abbreviateAttendees(attendees: unknown[] | null): string {
  if (!attendees || attendees.length === 0) return '';
  const names = attendees.slice(0, 3).map((a) => {
    if (typeof a === 'string') return a;
    if (a && typeof a === 'object' && 'email' in a) {
      const obj = a as { displayName?: string; email?: string };
      if (obj.displayName) return obj.displayName.split(' ')[0];
      if (obj.email) return obj.email.split('@')[0];
    }
    return '';
  }).filter(Boolean);
  const extra = attendees.length - 3;
  if (extra > 0) return `${names.join(', ')} +${extra}`;
  return names.join(', ');
}

function hasConference(event: CalendarEvent): boolean {
  return !!(event.conference_data && Object.keys(event.conference_data).length > 0);
}

function ConferenceIcon() {
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
      className="text-primary shrink-0"
      aria-label="Video call"
    >
      <polygon points="23 7 16 12 23 17 23 7" />
      <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
    </svg>
  );
}

function EventRow({ event }: { event: CalendarEvent }) {
  const time = event.all_day
    ? 'All day'
    : `${formatTime(event.start_time)}\u2013${formatTime(event.end_time)}`;

  const attendeeStr = abbreviateAttendees(event.attendees);

  return (
    <a
      href={event.html_link ?? undefined}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 py-1.5 px-1 -mx-1 rounded hover:bg-raised/50 transition-colors duration-100 cursor-pointer group"
    >
      <span className="text-xs text-muted tabular-nums w-[90px] shrink-0">{time}</span>
      <span className="text-sm text-foreground flex-1 min-w-0 truncate">{event.title}</span>
      {attendeeStr && (
        <span className="text-[10px] text-muted shrink-0 max-w-[120px] truncate">
          {attendeeStr}
        </span>
      )}
      {hasConference(event) && <ConferenceIcon />}
    </a>
  );
}

function Skeleton() {
  return (
    <Card>
      <CardHeader className="py-2 px-3">
        <div className="h-3 w-20 rounded bg-raised animate-pulse" />
      </CardHeader>
      <CardBody className="py-1.5 px-3 space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3 py-1.5">
            <div className="h-3 w-[90px] rounded bg-raised animate-pulse" />
            <div className="h-3.5 w-40 rounded bg-raised animate-pulse" />
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

export function CalendarWidget() {
  const now = new Date();
  const end = new Date(now);
  end.setDate(end.getDate() + 2);

  const authStatus = $api.useQuery('get', '/api/v1/calendar/auth-status');
  const events = $api.useQuery(
    'get',
    '/api/v1/calendar/events',
    {
      params: {
        query: {
          start: now.toISOString(),
          end: end.toISOString(),
          limit: 20,
        },
      },
    },
    {
      enabled: authStatus.data?.authenticated === true,
      refetchInterval: 60_000,
    },
  );

  // Don't render if not connected
  if (authStatus.isLoading) return null;
  if (!authStatus.data?.authenticated) return null;

  if (events.isLoading) return <Skeleton />;

  if (events.isError) {
    return (
      <Card>
        <CardHeader className="py-2 px-3">
          <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">Calendar</h4>
        </CardHeader>
        <CardBody className="py-3 px-3">
          <p className="text-sm text-muted">Failed to load calendar</p>
        </CardBody>
      </Card>
    );
  }

  const eventList = events.data ?? [];
  if (eventList.length === 0) {
    return (
      <Card>
        <CardHeader className="py-2 px-3">
          <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">Calendar</h4>
        </CardHeader>
        <CardBody className="py-3 px-3">
          <p className="text-sm text-muted">No upcoming events</p>
        </CardBody>
      </Card>
    );
  }

  const grouped = groupByDay(eventList);

  return (
    <div className="space-y-2">
      {[...grouped.entries()].map(([dayLabel, dayEvents]) => (
        <Card key={dayLabel}>
          <CardHeader className="py-2 px-3">
            <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">
              {dayLabel}
            </h4>
          </CardHeader>
          <CardBody className="py-1.5 px-3 space-y-0.5">
            {dayEvents.map((event) => (
              <EventRow key={event.id} event={event} />
            ))}
          </CardBody>
        </Card>
      ))}
    </div>
  );
}
