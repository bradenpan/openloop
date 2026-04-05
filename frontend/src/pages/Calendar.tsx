import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../api/hooks';
import type { components } from '../api/types';
import { Card, CardBody, Button } from '../components/ui';

type CalendarEvent = components['schemas']['CalendarEventResponse'];

// ─── Helpers ─────────────────────────────────────────────────────────────────

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
  return attendees.map((a) => {
    if (typeof a === 'string') return a;
    if (a && typeof a === 'object' && 'email' in a) {
      const obj = a as { displayName?: string; email?: string };
      return obj.displayName ?? obj.email ?? '';
    }
    return '';
  }).filter(Boolean).join(', ');
}

function getConferenceLink(event: CalendarEvent): string | null {
  if (!event.conference_data) return null;
  const data = event.conference_data as { entryPoints?: Array<{ entryPointType?: string; uri?: string }> };
  if (data.entryPoints) {
    const video = data.entryPoints.find((ep) => ep.entryPointType === 'video');
    if (video?.uri) return video.uri;
  }
  return null;
}

// ─── Conference icon ─────────────────────────────────────────────────────────

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

// ─── Sync icon ───────────────────────────────────────────────────────────────

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

// ─── Event row (expandable) ──────────────────────────────────────────────────

function EventRow({ event }: { event: CalendarEvent }) {
  const [expanded, setExpanded] = useState(false);

  const time = event.all_day
    ? 'All day'
    : `${formatTime(event.start_time)}\u2013${formatTime(event.end_time)}`;

  const conferenceLink = getConferenceLink(event);

  return (
    <div className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 py-2.5 px-3 text-left hover:bg-raised/50 transition-colors duration-100 cursor-pointer"
      >
        <span className="text-xs text-muted tabular-nums w-[100px] shrink-0">{time}</span>
        <span className="text-sm text-foreground flex-1 min-w-0 truncate">{event.title}</span>
        {conferenceLink && <ConferenceIcon />}
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className={`text-muted shrink-0 transition-transform duration-150 ${expanded ? 'rotate-180' : ''}`}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-0 space-y-2 text-sm">
          {event.location && (
            <div className="flex items-start gap-2">
              <span className="text-muted shrink-0">Location:</span>
              <span className="text-foreground">{event.location}</span>
            </div>
          )}

          {event.attendees && event.attendees.length > 0 && (
            <div className="flex items-start gap-2">
              <span className="text-muted shrink-0">Attendees:</span>
              <span className="text-foreground">{abbreviateAttendees(event.attendees)}</span>
            </div>
          )}

          {event.description && (
            <div className="flex items-start gap-2">
              <span className="text-muted shrink-0">Description:</span>
              <span className="text-foreground whitespace-pre-wrap line-clamp-4">
                {event.description}
              </span>
            </div>
          )}

          <div className="flex items-center gap-3 pt-1">
            {event.html_link && (
              <a
                href={event.html_link}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-primary hover:underline"
              >
                Open in Google Calendar
              </a>
            )}
            {conferenceLink && (
              <a
                href={conferenceLink}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-primary hover:underline"
              >
                Join video call
              </a>
            )}
          </div>
        </div>
      )}
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
      {[1, 2].map((g) => (
        <div key={g} className="space-y-2">
          <div className="h-4 w-20 rounded bg-raised animate-pulse" />
          <Card>
            <CardBody className="space-y-3 py-2 px-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-3 py-1.5">
                  <div className="h-3 w-[100px] rounded bg-raised animate-pulse" />
                  <div className="h-3.5 w-48 rounded bg-raised animate-pulse" />
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

export default function Calendar() {
  const queryClient = useQueryClient();
  const [syncError, setSyncError] = useState<string | null>(null);

  const now = new Date();
  const end = new Date(now);
  end.setDate(end.getDate() + 14);

  const authStatus = $api.useQuery('get', '/api/v1/calendar/auth-status');
  const events = $api.useQuery(
    'get',
    '/api/v1/calendar/events',
    {
      params: {
        query: {
          start: now.toISOString(),
          end: end.toISOString(),
          limit: 200,
        },
      },
    },
    {
      enabled: authStatus.data?.authenticated === true,
      refetchInterval: 60_000,
    },
  );

  const syncMutation = $api.useMutation('post', '/api/v1/calendar/sync', {
    onSuccess: () => {
      setSyncError(null);
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/calendar/events'] });
    },
    onError: () => {
      setSyncError('Sync failed \u2014 try again');
    },
  });

  if (authStatus.isLoading || events.isLoading) return <PageSkeleton />;

  if (!authStatus.data?.authenticated) {
    return (
      <div className="max-w-3xl">
        <h1 className="text-xl font-bold text-foreground mb-4">Calendar</h1>
        <Card>
          <CardBody className="py-8 text-center">
            <p className="text-sm text-muted">
              Google Calendar is not connected. Go to Settings to connect your account.
            </p>
          </CardBody>
        </Card>
      </div>
    );
  }

  if (events.isError) {
    return (
      <div className="space-y-6 max-w-3xl">
        <h1 className="text-xl font-bold text-foreground">Calendar</h1>
        <Card>
          <CardBody className="py-8 text-center">
            <p className="text-sm text-muted">Failed to load calendar events</p>
          </CardBody>
        </Card>
      </div>
    );
  }

  const eventList = events.data ?? [];
  const grouped = groupByDay(eventList);

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-foreground">Calendar</h1>
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
          Synced: {syncMutation.data.added} added, {syncMutation.data.updated} updated, {syncMutation.data.removed} removed
        </p>
      )}

      {/* Event list grouped by day */}
      {eventList.length === 0 ? (
        <Card>
          <CardBody className="py-8 text-center">
            <p className="text-sm text-muted">No upcoming events in the next 14 days.</p>
          </CardBody>
        </Card>
      ) : (
        [...grouped.entries()].map(([dayLabel, dayEvents]) => (
          <section key={dayLabel}>
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-2">
              {dayLabel}
            </h2>
            <Card>
              <CardBody className="p-0">
                {dayEvents.map((event) => (
                  <EventRow key={event.id} event={event} />
                ))}
              </CardBody>
            </Card>
          </section>
        ))
      )}
    </div>
  );
}
