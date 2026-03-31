import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { $api } from '../api/hooks';
import { Badge } from '../components/ui';
import { TodoPanel } from '../components/space/todo-panel';
import { KanbanBoard } from '../components/space/kanban-board';
import { TableView } from '../components/space/table-view';
import { ConversationSidebar } from '../components/space/conversation-sidebar';
import { DocumentPanel } from '../components/space/document-panel';
import { DocumentViewer } from '../components/space/document-viewer';

const DEFAULT_COLUMNS = ['Idea', 'Scoping', 'To Do', 'In Progress', 'Done'];

type CenterView = 'board' | 'table' | 'documents';

function getViewStorageKey(spaceId: string) {
  return `openloop:space-view:${spaceId}`;
}

function loadSavedView(spaceId: string): CenterView {
  try {
    const saved = localStorage.getItem(getViewStorageKey(spaceId));
    if (saved === 'board' || saved === 'table' || saved === 'documents') return saved;
  } catch {
    // ignore
  }
  return 'board';
}

function saveView(spaceId: string, view: CenterView) {
  try {
    localStorage.setItem(getViewStorageKey(spaceId), view);
  } catch {
    // ignore
  }
}

export default function Space() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const [todoCollapsed, setTodoCollapsed] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const [centerView, setCenterViewState] = useState<CenterView>(() =>
    spaceId ? loadSavedView(spaceId) : 'board',
  );
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);

  function setCenterView(view: CenterView) {
    setCenterViewState(view);
    if (spaceId) saveView(spaceId, view);
  }

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

        {/* View tabs */}
        <div className="ml-auto flex items-center gap-1 bg-raised rounded-md p-0.5">
          {space.board_enabled && (
            <>
              <button
                onClick={() => setCenterView('board')}
                className={`px-3 py-1 text-xs font-medium rounded cursor-pointer transition-colors ${
                  centerView === 'board'
                    ? 'bg-surface text-foreground shadow-sm'
                    : 'text-muted hover:text-foreground'
                }`}
              >
                Board
              </button>
              <button
                onClick={() => setCenterView('table')}
                className={`px-3 py-1 text-xs font-medium rounded cursor-pointer transition-colors ${
                  centerView === 'table'
                    ? 'bg-surface text-foreground shadow-sm'
                    : 'text-muted hover:text-foreground'
                }`}
              >
                Table
              </button>
            </>
          )}
          <button
            onClick={() => setCenterView('documents')}
            className={`px-3 py-1 text-xs font-medium rounded cursor-pointer transition-colors ${
              centerView === 'documents'
                ? 'bg-surface text-foreground shadow-sm'
                : 'text-muted hover:text-foreground'
            }`}
          >
            Documents
          </button>
        </div>
      </div>

      {/* 3-column layout */}
      <div className="flex flex-1 min-h-0">
        <TodoPanel
          spaceId={spaceId}
          collapsed={todoCollapsed}
          onToggle={() => setTodoCollapsed((v) => !v)}
        />

        {/* Center column */}
        {centerView === 'board' ? (
          <KanbanBoard
            spaceId={spaceId}
            boardColumns={boardColumns}
            boardEnabled={space.board_enabled}
          />
        ) : centerView === 'table' ? (
          <TableView
            spaceId={spaceId}
            boardColumns={boardColumns}
            boardEnabled={space.board_enabled}
          />
        ) : (
          <div className="flex-1 min-w-0">
            <DocumentPanel
              spaceId={spaceId}
              onSelectDocument={(id) => setSelectedDocId(id)}
            />
          </div>
        )}

        <ConversationSidebar
          spaceId={spaceId}
          collapsed={chatCollapsed}
          onToggle={() => setChatCollapsed((v) => !v)}
        />
      </div>

      {/* Document viewer slide-over */}
      <DocumentViewer
        documentId={selectedDocId}
        open={selectedDocId != null}
        onClose={() => setSelectedDocId(null)}
      />
    </div>
  );
}
