import { useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { $api } from '../api/hooks';
import { Badge } from '../components/ui';
import { DocumentViewer } from '../components/space/document-viewer';
import { LayoutEditor } from '../components/space/layout-editor';
import { getWidgetComponent, sizeToTrack } from '../components/space/widget-registry';
import type { components } from '../api/types';

type WidgetResponse = components['schemas']['WidgetResponse'];

// --- View toggle helpers (board/table switching) ---

type CenterView = 'board' | 'table';

function getViewStorageKey(spaceId: string) {
  return `openloop:space-view:${spaceId}`;
}

function loadSavedView(spaceId: string): CenterView {
  try {
    const saved = localStorage.getItem(getViewStorageKey(spaceId));
    if (saved === 'board' || saved === 'table') return saved;
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

// --- Widget grid helpers ---

/** Widgets with size "full" get their own row; everything else shares one row. */
function buildGridRows(widgets: WidgetResponse[]): WidgetResponse[][] {
  const rows: WidgetResponse[][] = [];
  let currentRow: WidgetResponse[] = [];

  for (const w of widgets) {
    if (w.size === 'full') {
      if (currentRow.length > 0) {
        rows.push(currentRow);
        currentRow = [];
      }
      rows.push([w]);
    } else {
      currentRow.push(w);
    }
  }

  if (currentRow.length > 0) {
    rows.push(currentRow);
  }

  return rows;
}

function gridTemplateForRow(row: WidgetResponse[]): string {
  if (row.length === 1 && row[0].size === 'full') {
    return '1fr';
  }
  return row.map((w) => sizeToTrack(w.size)).join(' ');
}

// --- Main component ---

export default function Space() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [layoutEditorOpen, setLayoutEditorOpen] = useState(false);
  const [centerView, setCenterViewState] = useState<CenterView>(() =>
    spaceId ? loadSavedView(spaceId) : 'board',
  );

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

  // Determine if we need the board/table view toggle
  const hasKanban = widgets.some((w) => w.widget_type === 'kanban_board');
  const hasTable = widgets.some((w) => w.widget_type === 'data_table');
  const showViewToggle = hasKanban && hasTable;

  // Filter widgets: if both kanban and table exist, only show the active one
  const visibleWidgets = useMemo(() => {
    if (!hasKanban || !hasTable) return widgets;
    return widgets.filter((w) => {
      if (w.widget_type === 'kanban_board') return centerView === 'board';
      if (w.widget_type === 'data_table') return centerView === 'table';
      return true;
    });
  }, [widgets, hasKanban, hasTable, centerView]);

  const gridRows = useMemo(() => buildGridRows(visibleWidgets), [visibleWidgets]);

  if (!spaceId) {
    return <p className="text-muted">No space selected.</p>;
  }

  if (spaceLoading || layoutLoading) {
    return <p className="text-muted">Loading space...</p>;
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

        {/* Gear icon — opens layout editor */}
        <button
          onClick={() => setLayoutEditorOpen(true)}
          className="ml-auto p-1.5 rounded-md text-muted hover:text-foreground hover:bg-raised transition-colors cursor-pointer"
          aria-label="Open layout editor"
          title="Layout settings"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="2.5" />
            <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.42 1.42M11.18 11.18l1.42 1.42M12.6 3.4l-1.42 1.42M4.82 11.18l-1.42 1.42" />
          </svg>
        </button>

        {/* View tabs — only shown when both kanban_board and data_table widgets exist */}
        {showViewToggle && (
          <div className="flex items-center gap-1 bg-raised rounded-md p-0.5">
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
          </div>
        )}
      </div>

      {/* Widget grid */}
      {widgets.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted text-sm">
            No widgets configured. Open layout settings to add widgets.
          </p>
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex flex-col">
          {gridRows.map((row) => (
            <div
              key={row.map((w) => w.id).join('-')}
              className="flex-1 min-h-0"
              style={{
                display: 'grid',
                gridTemplateColumns: gridTemplateForRow(row),
              }}
            >
              {row.map((widget) => (
                <WidgetRenderer
                  key={widget.id}
                  widget={widget}
                  spaceId={spaceId}
                  onSelectDocument={(id) => setSelectedDocId(id)}
                />
              ))}
            </div>
          ))}
        </div>
      )}

      {/* Document viewer slide-over */}
      <DocumentViewer
        documentId={selectedDocId}
        open={selectedDocId != null}
        onClose={() => setSelectedDocId(null)}
      />

      {/* Layout editor slide-over */}
      <LayoutEditor
        spaceId={spaceId}
        open={layoutEditorOpen}
        onClose={() => setLayoutEditorOpen(false)}
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
