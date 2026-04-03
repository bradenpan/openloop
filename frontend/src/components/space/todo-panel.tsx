import { useState, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button } from '../ui';
import { ItemDetailPanel } from './item-detail-panel';
import type { components } from '../../api/types';

type ItemResponse = components['schemas']['ItemResponse'];

interface TaskListPanelProps {
  spaceId: string;
  collapsed: boolean;
  onToggle: () => void;
}

export function TaskListPanel({ spaceId, collapsed, onToggle }: TaskListPanelProps) {
  const queryClient = useQueryClient();
  const [newTitle, setNewTitle] = useState('');
  const [showDone, setShowDone] = useState(false);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);

  // Fetch the space to get board_columns
  const { data: space } = $api.useQuery('get', '/api/v1/spaces/{space_id}', {
    params: { path: { space_id: spaceId } },
  });
  const boardColumns: string[] = space?.board_columns ?? ['todo', 'in_progress', 'done'];

  // Fetch tasks — when showDone is false, only fetch open tasks; when true, fetch all
  const queryParams: Record<string, unknown> = {
    space_id: spaceId,
    item_type: 'task',
    archived: false,
  };
  if (!showDone) {
    queryParams.is_done = false;
  }

  const { data: itemsData, isLoading } = $api.useQuery('get', '/api/v1/items', {
    params: { query: queryParams as Record<string, string | boolean> },
  });
  const items: ItemResponse[] = itemsData ?? [];

  const openItems = useMemo(() => items.filter((i) => !i.is_done), [items]);
  const doneItems = useMemo(() => items.filter((i) => i.is_done), [items]);

  const createItem = $api.useMutation('post', '/api/v1/items', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
      setNewTitle('');
    },
  });

  const updateItem = $api.useMutation('patch', '/api/v1/items/{item_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
    },
  });

  const moveItem = $api.useMutation('post', '/api/v1/items/{item_id}/move', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
    },
  });

  function handleAdd(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key !== 'Enter' || !newTitle.trim()) return;
    createItem.mutate({
      body: { space_id: spaceId, title: newTitle.trim(), item_type: 'task' },
    });
  }

  function handleToggleDone(itemId: string, currentDone: boolean) {
    updateItem.mutate({
      params: { path: { item_id: itemId } },
      body: { is_done: !currentDone },
    });
  }

  function handleStageChange(itemId: string, newStage: string) {
    moveItem.mutate({
      params: { path: { item_id: itemId } },
      body: { stage: newStage },
    });
  }

  if (collapsed) {
    return (
      <div className="flex flex-col items-center py-3 w-10 shrink-0 bg-surface border-r border-border">
        <button
          onClick={onToggle}
          className="text-muted hover:text-foreground transition-colors p-1.5 rounded-md hover:bg-raised cursor-pointer"
          aria-label="Expand task panel"
          title="Tasks"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="2" y="2" width="12" height="12" rx="2" />
            <path d="M5 8h6M8 5v6" />
          </svg>
        </button>
        <span className="text-[10px] text-muted mt-1 [writing-mode:vertical-rl] rotate-180">Tasks</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col w-72 min-w-[256px] shrink-0 bg-surface border-r border-border">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-border flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          Tasks
          {openItems.length > 0 && (
            <span className="ml-1.5 text-xs text-muted font-normal">({openItems.length})</span>
          )}
        </h3>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowDone((v) => !v)}
            className={`text-xs px-1.5 py-0.5 rounded transition-colors cursor-pointer ${
              showDone
                ? 'bg-primary/10 text-primary'
                : 'text-muted hover:text-foreground hover:bg-raised'
            }`}
            title={showDone ? 'Hide completed' : 'Show completed'}
          >
            {showDone ? 'Hide done' : 'Show done'}
          </button>
          <button
            onClick={onToggle}
            className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised cursor-pointer"
            aria-label="Collapse task panel"
          >
            &#x2190;
          </button>
        </div>
      </div>

      {/* Add input */}
      <div className="px-3 py-2 border-b border-border">
        <input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={handleAdd}
          placeholder="Add task, press Enter"
          disabled={createItem.isPending}
          className="w-full bg-raised text-foreground border border-border rounded-md px-2.5 py-1.5 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
        />
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-auto">
        {isLoading && <p className="px-3 py-4 text-sm text-muted">Loading...</p>}

        {!isLoading && items.length === 0 && (
          <p className="px-3 py-4 text-sm text-muted italic">No tasks yet</p>
        )}

        {/* Open tasks */}
        {openItems.map((item) => (
          <TaskRow
            key={item.id}
            item={item}
            boardColumns={boardColumns}
            onToggleDone={() => handleToggleDone(item.id, item.is_done)}
            onStageChange={(stage) => handleStageChange(item.id, stage)}
            onClick={() => setSelectedItemId(item.id)}
          />
        ))}

        {/* Done tasks */}
        {showDone && doneItems.length > 0 && (
          <>
            <div className="px-3 pt-3 pb-1">
              <span className="text-[11px] text-muted uppercase tracking-wider font-medium">
                Completed ({doneItems.length})
              </span>
            </div>
            {doneItems.map((item) => (
              <TaskRow
                key={item.id}
                item={item}
                boardColumns={boardColumns}
                onToggleDone={() => handleToggleDone(item.id, item.is_done)}
                onStageChange={(stage) => handleStageChange(item.id, stage)}
                onClick={() => setSelectedItemId(item.id)}
              />
            ))}
          </>
        )}
      </div>

      {/* Item detail panel */}
      <ItemDetailPanel
        itemId={selectedItemId}
        open={selectedItemId != null}
        onClose={() => setSelectedItemId(null)}
        boardColumns={boardColumns}
      />
    </div>
  );
}

interface TaskRowProps {
  item: ItemResponse;
  boardColumns: string[];
  onToggleDone: () => void;
  onStageChange: (stage: string) => void;
  onClick: () => void;
}

function TaskRow({ item, boardColumns, onToggleDone, onStageChange, onClick }: TaskRowProps) {
  return (
    <div
      className="group flex items-start gap-2 px-3 py-2 hover:bg-raised/50 transition-colors cursor-pointer"
      onClick={onClick}
    >
      <button
        onClick={(e) => {
          e.stopPropagation();
          onToggleDone();
        }}
        className={`mt-0.5 w-4 h-4 shrink-0 rounded border cursor-pointer transition-colors ${
          item.is_done
            ? 'bg-primary border-primary text-primary-foreground'
            : 'border-border hover:border-primary'
        } flex items-center justify-center`}
        aria-label={item.is_done ? 'Mark incomplete' : 'Mark complete'}
      >
        {item.is_done && (
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 5l2.5 2.5L8 3" />
          </svg>
        )}
      </button>

      <div className="flex-1 min-w-0">
        <p className={`text-sm leading-snug ${item.is_done ? 'line-through text-muted' : 'text-foreground'}`}>
          {item.title}
        </p>
        <div className="flex items-center gap-2 mt-0.5">
          {item.due_date && (
            <span className="text-[11px] text-muted">
              {new Date(item.due_date).toLocaleDateString()}
            </span>
          )}
          <select
            value={item.stage ?? boardColumns[0]}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => {
              e.stopPropagation();
              onStageChange(e.target.value);
            }}
            aria-label="Stage"
            className="text-[11px] text-muted bg-transparent border border-transparent hover:border-border rounded px-1 py-0 cursor-pointer focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {boardColumns.map((col) => (
              <option key={col} value={col}>{col}</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
