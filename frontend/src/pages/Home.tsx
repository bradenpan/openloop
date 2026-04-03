import { useState } from 'react';
import { $api } from '../api/hooks';
import { Skeleton } from '../components/ui';
import { Card, CardBody } from '../components/ui';
import { AttentionItems } from '../components/home/attention-items';
import { BackgroundTaskPanel } from '../components/home/background-task-panel';
import { SpaceList } from '../components/home/space-list';
import { TaskOverview } from '../components/home/todo-overview';
import { ConversationList } from '../components/home/conversation-list';
import { WelcomeCard } from '../components/home/welcome-card';
import { CreateSpaceModal } from '../components/home/create-space-modal';

function HomeSkeleton() {
  return (
    <div className="space-y-6 max-w-5xl">
      {/* Stat cards skeleton */}
      <Card>
        <CardBody className="flex items-center gap-6">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="flex flex-col items-center gap-1 px-4 py-2">
              <Skeleton width="2rem" height="1.75rem" rounded="rounded" />
              <Skeleton width="4rem" height="0.75rem" rounded="rounded" />
            </div>
          ))}
        </CardBody>
      </Card>
      {/* Spaces skeleton */}
      <section>
        <Skeleton width="4rem" height="0.75rem" rounded="rounded" className="mb-3" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardBody className="space-y-2">
                <Skeleton width="6rem" height="1rem" rounded="rounded" />
                <Skeleton height="0.75rem" rounded="rounded" />
                <Skeleton width="4rem" height="1.25rem" rounded="rounded-full" />
              </CardBody>
            </Card>
          ))}
        </div>
      </section>
      {/* Tasks skeleton */}
      <section>
        <Skeleton width="3rem" height="0.75rem" rounded="rounded" className="mb-3" />
        <Card>
          <CardBody className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-3 py-1.5">
                <Skeleton width="1rem" height="1rem" rounded="rounded" />
                <Skeleton width="12rem" height="0.875rem" rounded="rounded" />
              </div>
            ))}
          </CardBody>
        </Card>
      </section>
    </div>
  );
}

export default function Home() {
  const [welcomeModalOpen, setWelcomeModalOpen] = useState(false);

  const dashboard = $api.useQuery('get', '/api/v1/home/dashboard');
  const spaces = $api.useQuery('get', '/api/v1/spaces');
  const tasks = $api.useQuery('get', '/api/v1/items', {
    params: { query: { item_type: 'task', is_done: false, archived: false } },
  });
  const conversations = $api.useQuery('get', '/api/v1/conversations');
  const agents = $api.useQuery('get', '/api/v1/agents');
  const backupStatus = $api.useQuery('get', '/api/v1/system/backup-status', {}, {
    staleTime: 5 * 60 * 1000,
  });

  const allLoading = dashboard.isLoading || spaces.isLoading;

  const isFirstRun =
    !dashboard.isLoading &&
    !spaces.isLoading &&
    dashboard.data?.total_spaces === 0;

  if (allLoading) return <HomeSkeleton />;

  return (
    <div className="space-y-6 max-w-5xl">
      {/* First-run state */}
      {isFirstRun && (
        <>
          <WelcomeCard onCreateSpace={() => setWelcomeModalOpen(true)} />
          <CreateSpaceModal
            open={welcomeModalOpen}
            onClose={() => setWelcomeModalOpen(false)}
          />
        </>
      )}

      {/* 1. Attention Items */}
      <section>
        <AttentionItems dashboard={dashboard.data} isLoading={dashboard.isLoading} />
      </section>

      {/* Backup reminder (hidden on query error) */}
      {backupStatus.isSuccess && backupStatus.data?.needs_backup && (
        <p className="text-xs text-muted">
          {backupStatus.data.hours_since_backup != null
            ? `No backup in ${Math.floor(backupStatus.data.hours_since_backup / 24)} day(s) \u2014 run make backup`
            : 'No backups yet \u2014 run make backup'}
        </p>
      )}

      {/* 2. Active Agents */}
      <section>
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-2">
          Active Agents
        </h2>
        <BackgroundTaskPanel />
      </section>

      {/* 3. Spaces */}
      <section>
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-2">
          Spaces
        </h2>
        <SpaceList spaces={spaces.data} isLoading={spaces.isLoading} />
      </section>

      {/* 4. Tasks */}
      <section>
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-2">
          Tasks
        </h2>
        <TaskOverview
          tasks={tasks.data}
          spaces={spaces.data}
          isLoading={tasks.isLoading || spaces.isLoading}
        />
      </section>

      {/* 5. Recent Conversations */}
      <section>
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-2">
          Recent Conversations
        </h2>
        <ConversationList
          conversations={conversations.data}
          agents={agents.data}
          spaces={spaces.data}
          isLoading={conversations.isLoading || agents.isLoading || spaces.isLoading}
        />
      </section>
    </div>
  );
}
