import { Component, useEffect, useState, useMemo, type ReactNode, type ErrorInfo } from 'react';
import { useParams } from 'react-router-dom';
import { $api } from '../api/hooks';
import { Badge, Skeleton } from '../components/ui';
import { KanbanBoard } from '../components/space/kanban-board';
import { TableView } from '../components/space/table-view';
import { ChatTab } from '../components/space/chat-tab';
import { DocumentPanel } from '../components/space/document-panel';
import { DocumentViewer } from '../components/space/document-viewer';
import { SpaceSettings } from '../components/space/space-settings';
import { getWidgetComponent, DEFAULT_COLUMNS } from '../components/space/widget-registry';
import type { components } from '../api/types';

type WidgetResponse = components['schemas']['WidgetResponse'];

// --- View toggle helpers ---

type CenterView = 'board' | 'table' | 'files' | 'chat' | 'sheet';

function getViewStorageKey(spaceId: string) {
  return `openloop:space-view:${spaceId}`;
}

function loadSavedView(spaceId: string): CenterView {
  try {
    const saved = localStorage.getItem(getViewStorageKey(spaceId));
    if (saved === 'board' || saved === 'table' || saved === 'files' || saved === 'chat' || saved === 'sheet') return saved;
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

// --- Widget layout helpers ---

/** Widget types that render as sidebars (outside the content grid). */
const SIDEBAR_LEFT = new Set(['todo_panel']);
const SIDEBAR_RIGHT = new Set(['conversations']);

// --- Error boundary for widget area ---

class WidgetErrorBoundary extends Component<
  { children: ReactNode; onReset: () => void },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Widget error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-destructive font-medium mb-2">Something went wrong</p>
            <p className="text-sm text-muted mb-4">{this.state.error?.message}</p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                this.props.onReset();
              }}
              className="px-4 py-2 text-sm font-medium rounded-md bg-primary text-white hover:bg-primary/90 cursor-pointer"
            >
              Try Again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// --- Main component ---

export default function Space() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [centerView, setCenterViewState] = useState<CenterView>(() =>
    spaceId ? loadSavedView(spaceId) : 'board',
  );

  // Reset local state when navigating to a different space
  useEffect(() => {
    setSettingsOpen(false);
    setSelectedDocId(null);
    if (spaceId) {
      setCenterViewState(loadSavedView(spaceId));
    }
  }, [spaceId]);

  function setCenterView(view: CenterView) {
    setCenterViewState(view);
    if (spaceId) saveView(spaceId, view);
  }

  // Fetch space data (for header)
  const { data: space, isLoading: spaceLoading, error: spaceError } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}',
    { params: { path: { space_id: spaceId! } } },
    { enabled: !!spaceId },
  );

  // When space loads, apply DB default_view if no localStorage override exists
  useEffect(() => {
    if (space && spaceId) {
      const saved = localStorage.getItem(getViewStorageKey(spaceId));
      if (!saved && space.default_view) {
        const mapped: CenterView =
          space.default_view === 'table' ? 'table'
          : space.default_view === 'board' ? 'board'
          : 'table'; // 'list' and others default to table
        setCenterViewState(mapped);
      }
    }
  }, [space, spaceId]);

  // Fetch layout
  const { data: layoutData, isLoading: layoutLoading } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}/layout',
    { params: { path: { space_id: spaceId! } } },
    { enabled: !!spaceId },
  );

  const widgets = useMemo(() => {
    if (!layoutData?.widgets) return [];
    return [...layoutData.widgets].sort((a, b) => a.position - b.position);
  }, [layoutData]);

  // Core views (board/table/files) are always available — not dependent on widgets.
  // Google Sheet gets a "Sheet" tab when a google_sheet widget exists.
  const hasSheet = widgets.some((w) => w.widget_type === 'google_sheet');
  const sheetWidget = widgets.find((w) => w.widget_type === 'google_sheet');

  // Fall back if saved view is 'sheet' but no sheet widget exists
  useEffect(() => {
    if (centerView === 'sheet' && !hasSheet) {
      setCenterView('table');
    }
  }, [hasSheet, centerView]);

  // Space data for board/table components
  const boardColumns = space?.board_columns ?? DEFAULT_COLUMNS;
  const boardEnabled = space?.board_enabled ?? false;

  // Sidebar widgets rendered alongside the center view
  const sidebarWidgets = useMemo(() => {
    const left = widgets.filter((w) => SIDEBAR_LEFT.has(w.widget_type));
    const right = widgets.filter((w) => SIDEBAR_RIGHT.has(w.widget_type));
    return { left, right };
  }, [widgets]);

  if (!spaceId) {
    return <p className="text-muted">No space selected.</p>;
  }

  if (spaceLoading || layoutLoading) {
    return (
      <div className="flex flex-col h-full -m-6">
        {/* Header skeleton */}
        <div className="px-6 py-3 border-b border-border flex items-center gap-3 shrink-0 bg-surface/50">
          <Skeleton width="10rem" height="1.5rem" rounded="rounded" />
          <Skeleton width="4rem" height="1.25rem" rounded="rounded-full" />
        </div>
        {/* Widget grid skeleton */}
        <div className="flex-1 p-6 grid grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex flex-col gap-3">
              <Skeleton height="2rem" rounded="rounded" />
              <Skeleton height="8rem" rounded="rounded-lg" />
              <Skeleton height="4rem" rounded="rounded-lg" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (spaceError || !space) {
    return <p className="text-destructive">Failed to load space.</p>;
  }

  return (
    <div className="flex flex-col h-full -m-6">
      {/* Space header */}
      <div className="px-6 py-3 border-b border-border flex items-center gap-3 shrink-0 bg-surface/50">
        <h1 className="text-lg font-bold text-foreground">{space.name}</h1>
        <Badge>{space.template}</Badge>
        {space.description && (
          <span className="text-sm text-muted ml-2 truncate">{space.description}</span>
        )}

        {/* Gear icon — opens space settings */}
        <button
          onClick={() => setSettingsOpen(true)}
          className="ml-auto p-1.5 rounded-md text-muted hover:text-foreground hover:bg-raised transition-colors cursor-pointer"
          aria-label="Open space settings"
          title="Space settings"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="2.5" />
            <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.42 1.42M11.18 11.18l1.42 1.42M12.6 3.4l-1.42 1.42M4.82 11.18l-1.42 1.42" />
          </svg>
        </button>

        {/* View tabs — Board, Table, Chat, Files always present; Sheet shown when configured */}
        <div className="flex items-center gap-1 bg-raised rounded-md p-0.5">
          {(['board', 'table', 'chat', 'files'] as const).map((view) => (
            <button
              key={view}
              onClick={() => setCenterView(view)}
              className={`px-3 py-1 text-xs font-medium rounded cursor-pointer transition-colors ${
                centerView === view
                  ? 'bg-surface text-foreground shadow-sm'
                  : 'text-muted hover:text-foreground'
              }`}
            >
              {view === 'board' ? 'Board' : view === 'table' ? 'Table' : view === 'chat' ? 'Chat' : 'Files'}
            </button>
          ))}
          {hasSheet && (
            <button
              onClick={() => setCenterView('sheet')}
              className={`px-3 py-1 text-xs font-medium rounded cursor-pointer transition-colors ${
                centerView === 'sheet'
                  ? 'bg-surface text-foreground shadow-sm'
                  : 'text-muted hover:text-foreground'
              }`}
            >
              Sheet
            </button>
          )}
        </div>
      </div>

      {/* Main content area */}
      <WidgetErrorBoundary key={centerView} onReset={() => window.location.reload()}>
        {centerView === 'chat' ? (
          /* Chat tab manages its own layout (sidebar + tabs + widgets) */
          <div className="flex-1 min-h-0">
            <ChatTab spaceId={spaceId} widgets={widgets} onSelectDocument={(id) => setSelectedDocId(id)} />
          </div>
        ) : (
          <div className="flex-1 min-h-0 flex">
            {/* Left sidebars */}
            {sidebarWidgets.left.map((widget) => (
              <div key={widget.id} className="shrink-0 h-full">
                <WidgetRenderer
                  widget={widget}
                  spaceId={spaceId}
                  onSelectDocument={(id) => setSelectedDocId(id)}
                />
              </div>
            ))}

            {/* Center view — rendered directly, not from widget grid */}
            <div className="flex-1 min-w-0 min-h-0">
              {centerView === 'board' && (
                <KanbanBoard spaceId={spaceId} boardColumns={boardColumns} boardEnabled={boardEnabled} />
              )}
              {centerView === 'table' && (
                <TableView spaceId={spaceId} boardColumns={boardColumns} boardEnabled={boardEnabled} />
              )}
              {centerView === 'files' && (
                <DocumentPanel spaceId={spaceId} onSelectDocument={(id) => setSelectedDocId(id)} />
              )}
              {centerView === 'sheet' && sheetWidget && (
                <WidgetRenderer
                  widget={sheetWidget}
                  spaceId={spaceId}
                  onSelectDocument={(id) => setSelectedDocId(id)}
                />
              )}
            </div>

            {/* Right sidebars */}
            {sidebarWidgets.right.map((widget) => (
              <div key={widget.id} className="shrink-0 h-full">
                <WidgetRenderer
                  widget={widget}
                  spaceId={spaceId}
                  onSelectDocument={(id) => setSelectedDocId(id)}
                />
              </div>
            ))}
          </div>
        )}
      </WidgetErrorBoundary>

      {/* Document viewer slide-over */}
      <DocumentViewer
        documentId={selectedDocId}
        open={selectedDocId != null}
        onClose={() => setSelectedDocId(null)}
      />

      {/* Space settings slide-over */}
      <SpaceSettings
        spaceId={spaceId}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}

// --- Widget renderer ---

interface WidgetRendererProps {
  widget: WidgetResponse;
  spaceId: string;
  onSelectDocument: (documentId: string) => void;
}

function WidgetRenderer({ widget, spaceId, onSelectDocument }: WidgetRendererProps) {
  const Component = getWidgetComponent(widget.widget_type);

  return (
    <div className="min-h-0 min-w-0">
      <Component
        spaceId={spaceId}
        widgetId={widget.id}
        config={widget.config}
        size={widget.size}
        onSelectDocument={onSelectDocument}
      />
    </div>
  );
}
