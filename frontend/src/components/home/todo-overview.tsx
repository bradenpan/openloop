import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import type { components } from '../../api/types';
import { Card, CardHeader, CardBody } from '../ui';

type ItemResponse = components['schemas']['ItemResponse'];
type Space = components['schemas']['SpaceResponse'];

interface TaskOverviewProps {
  tasks: ItemResponse[] | undefined;
  spaces: Space[] | undefined;
  isLoading: boolean;
}

function Skeleton() {
  return (
    <Card>
      <CardBody className="space-y-2">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="flex items-center gap-3 py-1.5">
            <div className="h-4 w-4 rounded border border-border bg-raised animate-pulse" />
            <div className="h-3.5 w-48 rounded bg-raised animate-pulse" />
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

function TaskRow({ task }: { task: ItemResponse }) {
  const queryClient = useQueryClient();
  const updateItem = $api.useMutation('patch', '/api/v1/items/{item_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/home/dashboard'] });
    },
  });

  function toggle() {
    updateItem.mutate({
      params: { path: { item_id: task.id } },
      body: { is_done: !task.is_done },
    });
  }

  const isDueToday = task.due_date
    ? new Date(task.due_date).toDateString() === new Date().toDateString()
    : false;

  return (
    <label className="flex items-center gap-3 py-1 px-1 -mx-1 rounded hover:bg-raised/50 transition-colors duration-100 cursor-pointer group">
      <input
        type="checkbox"
        checked={task.is_done}
        onChange={toggle}
        disabled={updateItem.isPending}
        className="h-4 w-4 rounded border-border accent-primary cursor-pointer shrink-0"
      />
      <span
        className={`text-sm flex-1 min-w-0 truncate ${
          task.is_done ? 'line-through text-muted' : 'text-foreground'
        }`}
      >
        {task.title}
      </span>
      {task.stage && (
        <span className="text-[10px] text-muted bg-raised rounded px-1.5 py-0.5 shrink-0">
          {task.stage}
        </span>
      )}
      {isDueToday && !task.is_done && (
        <span className="text-xs text-warning shrink-0">due today</span>
      )}
    </label>
  );
}

export function TaskOverview({ tasks, spaces, isLoading }: TaskOverviewProps) {
  if (isLoading) return <Skeleton />;

  if (!tasks || tasks.length === 0) {
    return <p className="text-sm text-muted py-2">No tasks yet.</p>;
  }

  const spaceMap = new Map(spaces?.map((s) => [s.id, s.name]) ?? []);

  // Group by space
  const grouped = new Map<string, ItemResponse[]>();
  for (const task of tasks) {
    const key = task.space_id;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(task);
  }

  // Sort groups: undone first within each group
  for (const [, items] of grouped) {
    items.sort((a, b) => {
      if (a.is_done !== b.is_done) return a.is_done ? 1 : -1;
      return a.sort_position - b.sort_position;
    });
  }

  return (
    <div className="space-y-2">
      {[...grouped.entries()].map(([spaceId, items]) => (
        <Card key={spaceId}>
          <CardHeader className="py-2 px-3">
            <h4 className="text-xs font-semibold text-muted uppercase tracking-wide">
              {spaceMap.get(spaceId) ?? 'Unknown space'}
            </h4>
          </CardHeader>
          <CardBody className="py-1.5 px-3 space-y-0.5">
            {items.map((task) => (
              <TaskRow key={task.id} task={task} />
            ))}
          </CardBody>
        </Card>
      ))}
    </div>
  );
}
