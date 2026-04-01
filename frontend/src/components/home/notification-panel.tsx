import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { api } from '../../api/client';
import type { components } from '../../api/types';
import { Panel, Badge, Button } from '../ui';

type Notification = components['schemas']['NotificationResponse'];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function typeBadgeVariant(type: string): 'danger' | 'warning' | 'info' | 'default' {
  if (type.includes('failure') || type.includes('error')) return 'danger';
  if (type.includes('missed') || type.includes('stale') || type.includes('approval')) return 'warning';
  if (type.includes('info') || type.includes('success')) return 'info';
  return 'default';
}

function typeLabel(type: string): string {
  return type.replace(/_/g, ' ');
}

// ─── Notification item ────────────────────────────────────────────────────────

interface NotificationItemProps {
  notification: Notification;
  onDismiss: (id: string) => void;
  onClose: () => void;
}

function NotificationItem({ notification, onDismiss, onClose }: NotificationItemProps) {
  const navigate = useNavigate();

  const handleClick = async () => {
    // Mark as read first (fire and forget — UI will update via optimistic or refetch)
    onDismiss(notification.id);

    // Route based on type
    const type = notification.type;
    if (type === 'automation_failure' || type === 'automation_missed') {
      navigate('/automations');
      onClose();
    } else if (type === 'pending_approval' && notification.space_id) {
      navigate(`/space/${notification.space_id}`);
      onClose();
    } else if (notification.space_id) {
      navigate(`/space/${notification.space_id}`);
      onClose();
    }
    // else: stay on page, just mark read
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`w-full text-left px-4 py-3 flex gap-3 transition-colors duration-150 hover:bg-raised border-b border-border last:border-0 relative ${!notification.is_read ? 'bg-primary/5' : ''}`}
    >
      {/* Unread indicator */}
      {!notification.is_read && (
        <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-primary rounded-r" />
      )}

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2 mb-0.5">
          <span className="text-sm font-medium text-foreground leading-tight">
            {notification.title}
          </span>
          <Badge variant={typeBadgeVariant(notification.type)} className="text-[10px] shrink-0 mt-0.5">
            {typeLabel(notification.type)}
          </Badge>
        </div>
        {notification.body && (
          <p className="text-xs text-muted line-clamp-2 mb-1">{notification.body}</p>
        )}
        <p className="text-[11px] text-muted">{timeAgo(notification.created_at)}</p>
      </div>
    </button>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

interface NotificationPanelProps {
  open: boolean;
  onClose: () => void;
}

export function NotificationPanel({ open, onClose }: NotificationPanelProps) {
  const qc = useQueryClient();

  const { data, isLoading, error } = $api.useQuery(
    'get',
    '/api/v1/notifications',
    { params: { query: { is_read: false } } },
    { enabled: open, refetchOnWindowFocus: true }
  );

  const notifications: Notification[] = data ?? [];

  const markRead = async (id: string) => {
    try {
      await api.POST('/api/v1/notifications/{notification_id}/read', {
        params: { path: { notification_id: id } },
      });
      qc.invalidateQueries({ queryKey: ['get', '/api/v1/notifications'] });
      qc.invalidateQueries({ queryKey: ['get', '/api/v1/home/dashboard'] });
    } catch {
      // swallow
    }
  };

  const markAllRead = async () => {
    try {
      await api.POST('/api/v1/notifications/mark-all-read', {});
      qc.invalidateQueries({ queryKey: ['get', '/api/v1/notifications'] });
      qc.invalidateQueries({ queryKey: ['get', '/api/v1/home/dashboard'] });
    } catch {
      // swallow
    }
  };

  return (
    <Panel
      open={open}
      onClose={onClose}
      title="Notifications"
      width="400px"
    >
      {/* Toolbar: count + mark all read */}
      {notifications.length > 0 && (
        <div className="flex items-center justify-between -mt-2 mb-3">
          <span className="text-xs text-muted font-medium">
            {notifications.length} unread
          </span>
          <Button size="sm" variant="ghost" onClick={markAllRead}>
            Mark all read
          </Button>
        </div>
      )}

      {/* Content */}
      <div className="-mx-5 -mb-5">
          {isLoading && (
            <div className="space-y-px">
              {[1, 2, 3].map((i) => (
                <div key={i} className="px-4 py-3 border-b border-border">
                  <div className="flex gap-3">
                    <div className="flex-1 space-y-2">
                      <div className="h-4 w-48 rounded bg-raised animate-pulse" />
                      <div className="h-3 w-32 rounded bg-raised animate-pulse" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!isLoading && error && (
            <div className="py-16 text-center">
              <p className="text-sm font-medium text-foreground mb-1">Couldn't load notifications</p>
              <p className="text-xs text-muted">Something went wrong. Try again later.</p>
            </div>
          )}

          {!isLoading && !error && notifications.length === 0 && (
            <div className="py-16 text-center">
              <div className="text-3xl mb-3 select-none">&#10003;</div>
              <p className="text-sm font-medium text-foreground mb-1">All caught up</p>
              <p className="text-xs text-muted">No unread notifications.</p>
            </div>
          )}

          {!isLoading && !error && notifications.length > 0 && notifications.map((n) => (
            <NotificationItem
              key={n.id}
              notification={n}
              onDismiss={markRead}
              onClose={onClose}
            />
          ))}
      </div>
    </Panel>
  );
}
