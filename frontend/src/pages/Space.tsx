import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { $api } from '../api/hooks';
import { Badge } from '../components/ui';
import { TodoPanel } from '../components/space/todo-panel';
import { KanbanBoard } from '../components/space/kanban-board';
import { ConversationSidebar } from '../components/space/conversation-sidebar';

const DEFAULT_COLUMNS = ['Idea', 'Scoping', 'To Do', 'In Progress', 'Done'];

export default function Space() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const [todoCollapsed, setTodoCollapsed] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);

  const { data: spaceData, isLoading, error } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}',
    { params: { path: { space_id: spaceId! } } },
    { enabled: !!spaceId },
  );
  const space = spaceData;

  if (!spaceId) {
    return <p className="text-muted">No space selected.</p>;
  }

  if (isLoading) {
    return <p className="text-muted">Loading space...</p>;
  }

  if (error || !space) {
    return <p className="text-destructive">Failed to load space.</p>;
  }

  const boardColumns = space.board_columns ?? DEFAULT_COLUMNS;

  return (
    <div className="flex flex-col h-full -m-6">
      {/* Space header */}
      <div className="px-6 py-3 border-b border-border flex items-center gap-3 shrink-0 bg-surface/50">
        <h1 className="text-lg font-bold text-foreground">{space.name}</h1>
        <Badge>{space.template}</Badge>
        {space.description && (
          <span className="text-sm text-muted ml-2 truncate">{space.description}</span>
        )}
      </div>

      {/* 3-column layout */}
      <div className="flex flex-1 min-h-0">
        <TodoPanel
          spaceId={spaceId}
          collapsed={todoCollapsed}
          onToggle={() => setTodoCollapsed((v) => !v)}
        />

        <KanbanBoard
          spaceId={spaceId}
          boardColumns={boardColumns}
          boardEnabled={space.board_enabled}
        />

        <ConversationSidebar
          spaceId={spaceId}
          collapsed={chatCollapsed}
          onToggle={() => setChatCollapsed((v) => !v)}
        />
      </div>
    </div>
  );
}
