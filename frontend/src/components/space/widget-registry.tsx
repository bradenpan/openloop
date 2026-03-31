import { useState, type ComponentType } from 'react';
import { $api } from '../../api/hooks';
import { TodoPanel } from './todo-panel';
import { KanbanBoard } from './kanban-board';
import { TableView } from './table-view';
import { ConversationSidebar } from './conversation-sidebar';
import { DocumentPanel } from './document-panel';

// Standard widget props that every widget receives
export interface WidgetProps {
  spaceId: string;
  widgetId: string;
  config: Record<string, unknown> | null;
  size: string;
  /** Callback for widgets that need to trigger the document viewer */
  onSelectDocument?: (documentId: string) => void;
}

const DEFAULT_COLUMNS = ['Idea', 'Scoping', 'To Do', 'In Progress', 'Done'];

// --- Widget wrappers ---

function TodoPanelWidget({ spaceId }: WidgetProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <TodoPanel
      spaceId={spaceId}
      collapsed={collapsed}
      onToggle={() => setCollapsed((v) => !v)}
    />
  );
}

function KanbanBoardWidget({ spaceId }: WidgetProps) {
  const { data: space } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}',
    { params: { path: { space_id: spaceId } } },
  );

  const boardColumns = space?.board_columns ?? DEFAULT_COLUMNS;
  const boardEnabled = space?.board_enabled ?? false;

  return (
    <KanbanBoard
      spaceId={spaceId}
      boardColumns={boardColumns}
      boardEnabled={boardEnabled}
    />
  );
}

function DataTableWidget({ spaceId }: WidgetProps) {
  const { data: space } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}',
    { params: { path: { space_id: spaceId } } },
  );

  const boardColumns = space?.board_columns ?? DEFAULT_COLUMNS;
  const boardEnabled = space?.board_enabled ?? false;

  return (
    <TableView
      spaceId={spaceId}
      boardColumns={boardColumns}
      boardEnabled={boardEnabled}
    />
  );
}

function ConversationsSidebarWidget({ spaceId }: WidgetProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <ConversationSidebar
      spaceId={spaceId}
      collapsed={collapsed}
      onToggle={() => setCollapsed((v) => !v)}
    />
  );
}

function DocumentPanelWidget({ spaceId, onSelectDocument }: WidgetProps) {
  return (
    <DocumentPanel
      spaceId={spaceId}
      onSelectDocument={onSelectDocument ?? (() => {})}
    />
  );
}

function PlaceholderWidget({ widgetId, config }: WidgetProps) {
  const label = config?.label as string | undefined;

  return (
    <div className="flex flex-col items-center justify-center h-full bg-surface border border-border rounded-lg p-6 gap-2">
      <div className="w-10 h-10 rounded-lg bg-raised flex items-center justify-center">
        <svg
          width="20"
          height="20"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="text-muted"
        >
          <rect x="2" y="2" width="16" height="16" rx="3" />
          <path d="M7 7h6M7 10h6M7 13h4" />
        </svg>
      </div>
      <span className="text-sm font-medium text-foreground">
        {label ?? widgetId}
      </span>
      <span className="text-xs text-muted">Coming soon</span>
    </div>
  );
}

// --- Registry ---

const registry: Record<string, ComponentType<WidgetProps>> = {
  todo_panel: TodoPanelWidget,
  kanban_board: KanbanBoardWidget,
  data_table: DataTableWidget,
  conversations: ConversationsSidebarWidget,
  document_panel: DocumentPanelWidget,
  // Extended types render placeholders
  chart: PlaceholderWidget,
  stat_card: PlaceholderWidget,
  markdown: PlaceholderWidget,
  data_feed: PlaceholderWidget,
};

export function getWidgetComponent(
  widgetType: string,
): ComponentType<WidgetProps> {
  return registry[widgetType] ?? PlaceholderWidget;
}

/**
 * Map a widget size to a CSS grid column track value.
 * - small  -> sidebar-width flex track
 * - medium -> 2fr
 * - large  -> 3fr (main content)
 * - full   -> full row (handled separately)
 */
export function sizeToTrack(size: string): string {
  switch (size) {
    case 'small':
      return 'minmax(240px, 1fr)';
    case 'medium':
      return 'minmax(300px, 2fr)';
    case 'large':
      return 'minmax(400px, 3fr)';
    case 'full':
      return '1fr';
    default:
      return 'minmax(300px, 2fr)';
  }
}
