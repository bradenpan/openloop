import { useState, useMemo } from 'react';
import {
  DndContext,
  DragOverlay,
  closestCorners,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
  type DragOverEvent,
} from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useDroppable } from '@dnd-kit/core';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button, Badge } from '../ui';
import { BoardItemCard } from './board-item-card';
import { CreateItemModal } from './create-item-modal';
import { ItemDetailPanel } from './item-detail-panel';
import type { components } from '../../api/types';

type ItemResponse = components['schemas']['ItemResponse'];

interface KanbanBoardProps {
  spaceId: string;
  boardColumns: string[];
  boardEnabled: boolean;
}

export function KanbanBoard({ spaceId, boardColumns, boardEnabled }: KanbanBoardProps) {
  const queryClient = useQueryClient();
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [activeItem, setActiveItem] = useState<ItemResponse | null>(null);
  // Track which column an item is currently over during drag
  const [overColumn, setOverColumn] = useState<string | null>(null);
  // Done column visibility — collapsed by default
  const [hideDone, setHideDone] = useState(true);
  const hasDoneColumn = boardColumns.includes('done');
  const visibleColumns = useMemo(
    () => (hideDone && hasDoneColumn ? boardColumns.filter((c) => c !== 'done') : boardColumns),
    [boardColumns, hideDone, hasDoneColumn],
  );

  const { data: itemsData, isLoading } = $api.useQuery('get', '/api/v1/items', {
    params: { query: { space_id: spaceId, archived: false } },
  });
  const items = itemsData ?? [];

  const moveItem = $api.useMutation('post', '/api/v1/items/{item_id}/move', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
    },
  });

  // Group items by column
  const columnItems = useMemo(() => {
    const map: Record<string, ItemResponse[]> = {};
    for (const col of boardColumns) {
      map[col] = [];
    }
    for (const item of items) {
      const stage = item.stage ?? boardColumns[0];
      if (map[stage]) {
        map[stage].push(item);
      } else {
        // Item in unknown stage, put in first column
        map[boardColumns[0]]?.push(item);
      }
    }
    // Sort each column by sort_position
    for (const col of boardColumns) {
      map[col].sort((a, b) => a.sort_position - b.sort_position);
    }
    return map;
  }, [items, boardColumns]);

  // Override columnItems during drag to show preview
  const displayColumnItems = useMemo(() => {
    if (!activeItem || !overColumn) return columnItems;
    const result: Record<string, ItemResponse[]> = {};
    for (const col of boardColumns) {
      result[col] = columnItems[col].filter((i) => i.id !== activeItem.id);
    }
    if (result[overColumn]) {
      result[overColumn] = [...result[overColumn], activeItem];
    }
    return result;
  }, [columnItems, activeItem, overColumn, boardColumns]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  function handleDragStart(event: DragStartEvent) {
    const item = items.find((i) => i.id === event.active.id);
    if (item) {
      setActiveItem(item);
      setOverColumn(item.stage ?? boardColumns[0]);
    }
  }

  function handleDragOver(event: DragOverEvent) {
    const { over } = event;
    if (!over) return;
    const overId = String(over.id);

    // Check if over a column droppable
    if (boardColumns.includes(overId)) {
      setOverColumn(overId);
      return;
    }

    // Over another item -- find which column that item belongs to
    for (const col of boardColumns) {
      if (columnItems[col].some((i) => i.id === overId)) {
        setOverColumn(col);
        return;
      }
    }
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    setActiveItem(null);
    setOverColumn(null);

    if (!over) return;

    const itemId = String(active.id);
    const overId = String(over.id);

    // Determine target column
    let targetColumn: string | null = null;
    if (boardColumns.includes(overId)) {
      targetColumn = overId;
    } else {
      // Dropped onto an item -- find its column
      for (const col of boardColumns) {
        if (columnItems[col].some((i) => i.id === overId)) {
          targetColumn = col;
          break;
        }
      }
    }

    if (!targetColumn) return;

    // Find the item's current stage
    const item = items.find((i) => i.id === itemId);
    if (!item) return;
    const currentStage = item.stage ?? boardColumns[0];

    if (currentStage === targetColumn) return;

    moveItem.mutate({
      params: { path: { item_id: itemId } },
      body: { stage: targetColumn },
    });
  }

  if (!boardEnabled) {
    return (
      <div className="flex-1 flex items-center justify-center min-w-0">
        <div className="text-center">
          <p className="text-muted text-sm">Board not enabled for this space.</p>
          <p className="text-muted text-xs mt-1">Enable it in space settings.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Board header */}
      <div className="px-4 py-2.5 border-b border-border flex items-center justify-between shrink-0">
        <h3 className="text-sm font-semibold text-foreground">Board</h3>
        <div className="flex items-center gap-2">
          {hasDoneColumn && (
            <button
              onClick={() => setHideDone((v) => !v)}
              className={`text-xs px-2 py-1 rounded transition-colors cursor-pointer ${
                hideDone
                  ? 'text-muted hover:text-foreground hover:bg-raised'
                  : 'bg-primary/10 text-primary'
              }`}
            >
              {hideDone ? 'Show done' : 'Hide done'}
            </button>
          )}
          <Button size="sm" onClick={() => setCreateModalOpen(true)}>
            + Add Item
          </Button>
        </div>
      </div>

      {/* Board columns */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-sm text-muted">Loading board...</p>
        </div>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDragEnd={handleDragEnd}
        >
          <div className="flex-1 flex gap-0 overflow-x-auto">
            {visibleColumns.map((col) => (
              <BoardColumn
                key={col}
                columnName={col}
                items={displayColumnItems[col] ?? []}
                onItemClick={(id) => setSelectedItemId(id)}
                activeItemId={activeItem?.id ?? null}
              />
            ))}
          </div>

          <DragOverlay>
            {activeItem ? (
              <div className="bg-surface border border-primary rounded-lg p-3 shadow-lg opacity-90 max-w-[220px]">
                <p className="text-sm font-medium text-foreground">{activeItem.title}</p>
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      )}

      <CreateItemModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        spaceId={spaceId}
        boardColumns={boardColumns}
      />

      <ItemDetailPanel
        itemId={selectedItemId}
        open={selectedItemId != null}
        onClose={() => setSelectedItemId(null)}
        boardColumns={boardColumns}
      />
    </div>
  );
}

interface BoardColumnProps {
  columnName: string;
  items: ItemResponse[];
  onItemClick: (id: string) => void;
  activeItemId: string | null;
}

function BoardColumn({ columnName, items, onItemClick, activeItemId }: BoardColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id: columnName });
  const itemIds = items.map((i) => i.id);

  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col flex-1 min-w-[200px] max-w-[280px] border-r border-border last:border-r-0 transition-colors ${
        isOver ? 'bg-primary/5' : ''
      }`}
    >
      {/* Column header */}
      <div className="px-3 py-2 border-b border-border/50 flex items-center justify-between">
        <span className="text-xs font-semibold text-muted uppercase tracking-wider">{columnName}</span>
        <Badge variant="info" className="text-[10px]">
          {items.length}
        </Badge>
      </div>

      {/* Items */}
      <SortableContext items={itemIds} strategy={verticalListSortingStrategy}>
        <div className="flex-1 overflow-auto p-2 flex flex-col gap-2">
          {items.map((item) => (
            <BoardItemCard
              key={item.id}
              item={item}
              onClick={() => {
                if (activeItemId == null) onItemClick(item.id);
              }}
            />
          ))}

          {items.length === 0 && (
            <div className="flex-1 flex items-center justify-center min-h-[60px]">
              <p className="text-xs text-muted italic">Empty</p>
            </div>
          )}
        </div>
      </SortableContext>
    </div>
  );
}
