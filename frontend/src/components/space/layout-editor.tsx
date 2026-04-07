import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button } from '../ui';
import type { components } from '../../api/types';

type WidgetResponse = components['schemas']['WidgetResponse'];
type WidgetType = components['schemas']['WidgetType'];
type WidgetSize = components['schemas']['WidgetSize'];

// --- Widget metadata for the picker and card labels ---

interface WidgetMeta {
  type: WidgetType;
  label: string;
  description: string;
  icon: string;
}

const WIDGET_CATALOG: WidgetMeta[] = [
  { type: 'todo_panel', label: 'Task Panel', description: 'Lightweight task checklist', icon: '☑' },
  { type: 'kanban_board', label: 'Kanban Board', description: 'Drag-and-drop stage board', icon: '▦' },
  { type: 'data_table', label: 'Data Table', description: 'Sortable, filterable data grid', icon: '⊞' },
  { type: 'conversations', label: 'Conversations', description: 'Chat sidebar with agents', icon: '💬' },
  { type: 'google_sheet', label: 'Google Sheet', description: 'Embed and edit a Google Sheet', icon: '📊' },
  { type: 'chart', label: 'Chart', description: 'Data visualization (coming soon)', icon: '📈' },
  { type: 'stat_card', label: 'Stat Card', description: 'Key metrics at a glance (coming soon)', icon: '🔢' },
  { type: 'markdown', label: 'Notes', description: 'Markdown text panel (coming soon)', icon: '📝' },
  { type: 'data_feed', label: 'Data Feed', description: 'Live data stream (coming soon)', icon: '📡' },
];

const WIDGET_LABEL_MAP: Record<string, string> = Object.fromEntries(
  WIDGET_CATALOG.map((w) => [w.type, w.label]),
);

const WIDGET_ICON_MAP: Record<string, string> = Object.fromEntries(
  WIDGET_CATALOG.map((w) => [w.type, w.icon]),
);

const SIZE_OPTIONS: { value: WidgetSize; label: string }[] = [
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large', label: 'Large' },
  { value: 'full', label: 'Full' },
];

// --- Config notes per widget type ---

function getConfigNote(widgetType: string): string | null {
  switch (widgetType) {
    case 'kanban_board':
      return 'Board columns are managed in space settings.';
    case 'data_table':
      return 'Table fields are configured in the table view.';
    case 'google_sheet':
      return 'Sheet URL is configured from the widget in the space view.';
    default:
      return null;
  }
}

// --- Layout Editor Panel ---

interface LayoutEditorProps {
  spaceId: string;
}

export function LayoutEditor({ spaceId }: LayoutEditorProps) {
  const queryClient = useQueryClient();
  const [showPicker, setShowPicker] = useState(false);
  const [expandedWidgetId, setExpandedWidgetId] = useState<string | null>(null);
  const [pendingRemoveId, setPendingRemoveId] = useState<string | null>(null);

  const layoutQueryKey = ['get', '/api/v1/spaces/{space_id}/layout', { params: { path: { space_id: spaceId } } }] as const;

  const { data: layoutData } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}/layout',
    { params: { path: { space_id: spaceId } } },
  );

  const widgets = layoutData?.widgets
    ? [...layoutData.widgets].sort((a, b) => a.position - b.position)
    : [];

  // --- Mutations ---

  const addWidget = $api.useMutation('post', '/api/v1/spaces/{space_id}/layout/widgets', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [...layoutQueryKey] });
      setShowPicker(false);
    },
  });

  const updateWidget = $api.useMutation(
    'patch',
    '/api/v1/spaces/{space_id}/layout/widgets/{widget_id}',
    {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: [...layoutQueryKey] });
      },
    },
  );

  const removeWidget = $api.useMutation(
    'delete',
    '/api/v1/spaces/{space_id}/layout/widgets/{widget_id}',
    {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: [...layoutQueryKey] });
        setPendingRemoveId(null);
      },
    },
  );

  // --- Handlers ---

  function handleAdd(widgetType: WidgetType) {
    addWidget.mutate({
      params: { path: { space_id: spaceId } },
      body: { widget_type: widgetType, size: 'medium' },
    });
  }

  function handleRemove(widgetId: string) {
    removeWidget.mutate({
      params: { path: { space_id: spaceId, widget_id: widgetId } },
    });
  }

  function handleSizeChange(widgetId: string, size: WidgetSize) {
    updateWidget.mutate({
      params: { path: { space_id: spaceId, widget_id: widgetId } },
      body: { size },
    });
  }

  function handleMoveUp(widget: WidgetResponse, index: number) {
    if (index === 0) return;
    const targetPosition = widgets[index - 1].position;
    updateWidget.mutate({
      params: { path: { space_id: spaceId, widget_id: widget.id } },
      body: { position: targetPosition },
    });
  }

  function handleMoveDown(widget: WidgetResponse, index: number) {
    if (index >= widgets.length - 1) return;
    const targetPosition = widgets[index + 1].position;
    updateWidget.mutate({
      params: { path: { space_id: spaceId, widget_id: widget.id } },
      body: { position: targetPosition },
    });
  }

  function toggleConfig(widgetId: string) {
    setExpandedWidgetId((prev) => (prev === widgetId ? null : widgetId));
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Widget list */}
      {widgets.length === 0 && !showPicker && (
        <p className="text-sm text-muted py-4 text-center">
          No widgets yet. Add one to get started.
        </p>
      )}

      {widgets.map((widget, idx) => (
        <WidgetCard
          key={widget.id}
          widget={widget}
          index={idx}
          total={widgets.length}
          isExpanded={expandedWidgetId === widget.id}
          isPendingRemove={pendingRemoveId === widget.id}
          onSizeChange={(size) => handleSizeChange(widget.id, size)}
          onMoveUp={() => handleMoveUp(widget, idx)}
          onMoveDown={() => handleMoveDown(widget, idx)}
          onToggleConfig={() => toggleConfig(widget.id)}
          onRemoveClick={() => {
            if (pendingRemoveId === widget.id) {
              handleRemove(widget.id);
            } else {
              setPendingRemoveId(widget.id);
            }
          }}
          onRemoveCancel={() => setPendingRemoveId(null)}
          isRemoving={removeWidget.isPending}
        />
      ))}

      {/* Add widget button / picker */}
      {showPicker ? (
        <WidgetPicker
          existingTypes={widgets.map((w) => w.widget_type)}
          onSelect={handleAdd}
          onCancel={() => setShowPicker(false)}
          isAdding={addWidget.isPending}
        />
      ) : (
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setShowPicker(true)}
          className="mt-1 self-stretch"
        >
          <span className="mr-1">+</span> Add Widget
        </Button>
      )}
    </div>
  );
}

// --- Widget Card ---

interface WidgetCardProps {
  widget: WidgetResponse;
  index: number;
  total: number;
  isExpanded: boolean;
  isPendingRemove: boolean;
  onSizeChange: (size: WidgetSize) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onToggleConfig: () => void;
  onRemoveClick: () => void;
  onRemoveCancel: () => void;
  isRemoving: boolean;
}

function WidgetCard({
  widget,
  index,
  total,
  isExpanded,
  isPendingRemove,
  onSizeChange,
  onMoveUp,
  onMoveDown,
  onToggleConfig,
  onRemoveClick,
  onRemoveCancel,
  isRemoving,
}: WidgetCardProps) {
  const icon = WIDGET_ICON_MAP[widget.widget_type] ?? '▪';
  const label = WIDGET_LABEL_MAP[widget.widget_type] ?? widget.widget_type;
  const configNote = getConfigNote(widget.widget_type);

  return (
    <div className="bg-raised/50 border border-border rounded-lg overflow-hidden">
      {/* Main row */}
      <div className="flex items-center gap-2 px-3 py-2.5">
        {/* Icon */}
        <span className="text-base w-6 text-center shrink-0" aria-hidden="true">
          {icon}
        </span>

        {/* Name + size */}
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-foreground truncate">{label}</div>
          <div className="mt-0.5">
            <select
              value={widget.size}
              onChange={(e) => onSizeChange(e.target.value as WidgetSize)}
              className="text-xs bg-surface border border-border rounded px-1.5 py-0.5 text-muted cursor-pointer focus:outline-none focus:ring-1 focus:ring-primary"
              aria-label="Widget size"
            >
              {SIZE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Reorder arrows */}
        <div className="flex flex-col gap-0.5 shrink-0">
          <button
            onClick={onMoveUp}
            disabled={index === 0}
            className="text-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed p-0.5 rounded hover:bg-surface transition-colors cursor-pointer"
            aria-label="Move up"
            title="Move up"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7 11V3M3.5 6.5L7 3l3.5 3.5" />
            </svg>
          </button>
          <button
            onClick={onMoveDown}
            disabled={index >= total - 1}
            className="text-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed p-0.5 rounded hover:bg-surface transition-colors cursor-pointer"
            aria-label="Move down"
            title="Move down"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7 3v8M3.5 7.5L7 11l3.5-3.5" />
            </svg>
          </button>
        </div>

        {/* Configure button */}
        <button
          onClick={onToggleConfig}
          className={`p-1 rounded transition-colors cursor-pointer ${
            isExpanded
              ? 'text-primary bg-primary/10'
              : 'text-muted hover:text-foreground hover:bg-surface'
          }`}
          aria-label="Configure widget"
          title="Configure"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="7" cy="7" r="2.5" />
            <path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.76 2.76l1.06 1.06M10.18 10.18l1.06 1.06M11.24 2.76l-1.06 1.06M3.82 10.18l-1.06 1.06" />
          </svg>
        </button>

        {/* Remove button — click-twice pattern */}
        {isPendingRemove ? (
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={onRemoveClick}
              disabled={isRemoving}
              className="text-xs text-destructive font-medium px-1.5 py-0.5 rounded bg-destructive/10 hover:bg-destructive/20 transition-colors cursor-pointer disabled:opacity-50"
              title="Confirm removal"
            >
              {isRemoving ? '...' : 'Remove?'}
            </button>
            <button
              onClick={onRemoveCancel}
              className="text-xs text-muted hover:text-foreground px-1 py-0.5 cursor-pointer"
              title="Cancel"
            >
              No
            </button>
          </div>
        ) : (
          <button
            onClick={onRemoveClick}
            className="text-muted hover:text-destructive p-1 rounded hover:bg-destructive/10 transition-colors cursor-pointer shrink-0"
            aria-label="Remove widget"
            title="Remove"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
            </svg>
          </button>
        )}
      </div>

      {/* Configuration accordion */}
      {isExpanded && (
        <div className="px-3 pb-3 pt-0">
          <div className="border-t border-border pt-2.5 mt-0.5">
            {configNote ? (
              <p className="text-xs text-muted italic">{configNote}</p>
            ) : (
              <p className="text-xs text-muted italic">No configuration options.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// --- Widget Picker ---

interface WidgetPickerProps {
  existingTypes: string[];
  onSelect: (type: WidgetType) => void;
  onCancel: () => void;
  isAdding: boolean;
}

function WidgetPicker({ existingTypes, onSelect, onCancel, isAdding }: WidgetPickerProps) {
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-raised/50 border-b border-border flex items-center justify-between">
        <span className="text-xs font-medium text-foreground uppercase tracking-wider">
          Add Widget
        </span>
        <button
          onClick={onCancel}
          className="text-muted hover:text-foreground transition-colors p-0.5 rounded hover:bg-surface cursor-pointer"
          aria-label="Cancel"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M3 3l6 6M9 3l-6 6" />
          </svg>
        </button>
      </div>
      <div className="grid grid-cols-2 gap-1.5 p-2">
        {WIDGET_CATALOG.map((meta) => {
          const alreadyAdded = existingTypes.includes(meta.type);
          return (
            <button
              key={meta.type}
              onClick={() => onSelect(meta.type)}
              disabled={isAdding}
              className={`flex flex-col items-start gap-1 p-2.5 rounded-md border text-left transition-colors cursor-pointer disabled:opacity-50 ${
                alreadyAdded
                  ? 'border-border/50 bg-surface/50'
                  : 'border-border bg-surface hover:bg-raised hover:border-primary/30'
              }`}
            >
              <div className="flex items-center gap-1.5 w-full">
                <span className="text-sm" aria-hidden="true">
                  {meta.icon}
                </span>
                <span className="text-xs font-medium text-foreground truncate">
                  {meta.label}
                </span>
              </div>
              <span className="text-[10px] text-muted leading-tight">
                {meta.description}
              </span>
              {alreadyAdded && (
                <span className="text-[10px] text-primary font-medium">Added</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
