import { useState } from 'react';
import type { components } from '../../api/types';
import { Card, CardBody } from '../ui';
import { NotificationPanel } from './notification-panel';

type Dashboard = components['schemas']['DashboardResponse'];

interface AttentionItemsProps {
  dashboard: Dashboard | undefined;
  isLoading: boolean;
}

function StatCell({
  label,
  value,
  warn,
  onClick,
}: {
  label: string;
  value: number;
  warn?: boolean;
  onClick?: () => void;
}) {
  const clickable = !!onClick;
  const valueColor = warn && value > 0 ? 'text-warning' : 'text-foreground';

  if (clickable) {
    return (
      <button
        type="button"
        onClick={onClick}
        className="flex flex-col items-center gap-0.5 px-4 py-2 rounded-md transition-colors duration-150 hover:bg-raised cursor-pointer"
      >
        <span className={`text-2xl font-bold tabular-nums ${valueColor}`}>{value}</span>
        <span className="text-xs text-muted whitespace-nowrap underline decoration-dotted underline-offset-2">
          {label}
        </span>
      </button>
    );
  }

  return (
    <div className="flex flex-col items-center gap-0.5 px-4 py-2">
      <span className={`text-2xl font-bold tabular-nums ${valueColor}`}>{value}</span>
      <span className="text-xs text-muted whitespace-nowrap">{label}</span>
    </div>
  );
}

function Skeleton() {
  return (
    <Card>
      <CardBody className="flex items-center gap-6">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex flex-col items-center gap-1 px-4 py-2">
            <div className="h-7 w-8 rounded bg-raised animate-pulse" />
            <div className="h-3 w-16 rounded bg-raised animate-pulse" />
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

export function AttentionItems({ dashboard, isLoading }: AttentionItemsProps) {
  const [notifOpen, setNotifOpen] = useState(false);

  if (isLoading || !dashboard) return <Skeleton />;

  return (
    <>
      <Card>
        <CardBody className="flex flex-wrap items-center divide-x divide-border">
          <StatCell label="Pending Approvals" value={dashboard.pending_approvals} warn />
          <StatCell label="Open Tasks" value={dashboard.open_task_count} />
          <StatCell label="Active Conversations" value={dashboard.active_conversations} />
          <StatCell
            label="Unread Notifications"
            value={dashboard.unread_notifications}
            warn
            onClick={() => setNotifOpen(true)}
          />
          <StatCell label="Spaces" value={dashboard.total_spaces} />
        </CardBody>
      </Card>

      <NotificationPanel open={notifOpen} onClose={() => setNotifOpen(false)} />
    </>
  );
}
