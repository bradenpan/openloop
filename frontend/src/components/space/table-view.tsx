import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button, Badge } from '../ui';
import { ItemDetailPanel } from './item-detail-panel';
import { CreateRecordModal } from './create-record-modal';
import type { components } from '../../api/types';

type ItemResponse = components['schemas']['ItemResponse'];

interface FieldSchema {
  name: string;
  type: string;
  options?: string[];
}

// --- Column config types ---

interface ColumnDef {
  key: string;
  label: string;
  type: 'builtin' | 'custom';
  fieldType?: string; // text, number, date, select
  options?: string[];
  visible: boolean;
}

const BUILTIN_COLUMNS: Omit<ColumnDef, 'visible'>[] = [
  { key: 'title', label: 'Title', type: 'builtin', fieldType: 'text' },
  { key: 'stage', label: 'Stage', type: 'builtin', fieldType: 'select' },
  { key: 'priority', label: 'Priority', type: 'builtin', fieldType: 'number' },
  { key: 'due_date', label: 'Due Date', type: 'builtin', fieldType: 'date' },
  { key: 'created_at', label: 'Created', type: 'builtin', fieldType: 'date' },
];

function getStorageKey(spaceId: string) {
  return `openloop:table-columns:${spaceId}`;
}

function loadColumnConfig(spaceId: string): Record<string, boolean> | null {
  try {
    const raw = localStorage.getItem(getStorageKey(spaceId));
    if (raw) return JSON.parse(raw);
  } catch {
    // ignore
  }
  return null;
}

function saveColumnConfig(spaceId: string, config: Record<string, boolean>) {
  try {
    localStorage.setItem(getStorageKey(spaceId), JSON.stringify(config));
  } catch {
    // ignore
  }
}

// --- Sort config persistence ---

type SortField = string;
type SortOrder = 'asc' | 'desc';

function getSortStorageKey(spaceId: string) {
  return `openloop:table-sort:${spaceId}`;
}

function loadSortConfig(spaceId: string): { sortBy: string; sortOrder: string } | null {
  try {
    const raw = localStorage.getItem(getSortStorageKey(spaceId));
    if (raw) return JSON.parse(raw);
  } catch {
    // ignore
  }
  return null;
}

function saveSortConfig(spaceId: string, sortBy: string, sortOrder: string) {
  try {
    localStorage.setItem(getSortStorageKey(spaceId), JSON.stringify({ sortBy, sortOrder }));
  } catch {
    // ignore
  }
}

// --- Component ---

interface TableViewProps {
  spaceId: string;
  boardColumns: string[];
  boardEnabled: boolean;
}

export function TableView({ spaceId, boardColumns, boardEnabled }: TableViewProps) {
  const queryClient = useQueryClient();
  const [sortBy, setSortBy] = useState<SortField>(() => loadSortConfig(spaceId)?.sortBy ?? 'title');
  const [sortOrder, setSortOrder] = useState<SortOrder>(() => (loadSortConfig(spaceId)?.sortOrder as SortOrder) ?? 'asc');
  const [stageFilter, setStageFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [columnsPopoverOpen, setColumnsPopoverOpen] = useState(false);
  const [configVersion, setConfigVersion] = useState(0);

  // Reset sort state when space changes
  const spaceIdRef = useRef(spaceId);
  useEffect(() => {
    if (spaceIdRef.current !== spaceId) {
      spaceIdRef.current = spaceId;
      const saved = loadSortConfig(spaceId);
      setSortBy(saved?.sortBy ?? 'title');
      setSortOrder((saved?.sortOrder as SortOrder) ?? 'asc');
    }
  }, [spaceId]);

  // Persist sort preference
  useEffect(() => {
    saveSortConfig(spaceId, sortBy, sortOrder);
  }, [spaceId, sortBy, sortOrder]);

  // Fetch items with server-side sorting
  const serverSortable = ['title', 'created_at', 'updated_at', 'sort_position', 'priority', 'due_date', 'stage'];
  const useServerSort = serverSortable.includes(sortBy);

  const { data: itemsData, isLoading } = $api.useQuery('get', '/api/v1/items', {
    params: {
      query: {
        space_id: spaceId,
        archived: false,
        sort_by: useServerSort ? sortBy : undefined,
        sort_order: useServerSort ? sortOrder : undefined,
        stage: stageFilter || undefined,
        limit: 200,
      },
    },
  });
  const items = itemsData ?? [];

  // Fetch field schema
  const { data: fieldSchemaData } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}/field-schema',
    { params: { path: { space_id: spaceId } } },
  );
  const fieldSchema: FieldSchema[] = Array.isArray(fieldSchemaData) ? fieldSchemaData as FieldSchema[] : [];

  // Build column definitions
  const allColumns = useMemo<ColumnDef[]>(() => {
    const saved = loadColumnConfig(spaceId);
    const builtins = BUILTIN_COLUMNS.map((col) => ({
      ...col,
      visible: saved ? (saved[col.key] ?? true) : true,
      options: col.key === 'stage' ? boardColumns : undefined,
    }));
    const customs = fieldSchema.map((f) => ({
      key: `cf:${f.name}`,
      label: f.name,
      type: 'custom' as const,
      fieldType: f.type || 'text',
      options: f.options,
      visible: saved ? (saved[`cf:${f.name}`] ?? true) : true,
    }));
    return [...builtins, ...customs];
  }, [spaceId, fieldSchema, boardColumns, configVersion]);

  const visibleColumns = useMemo(() => allColumns.filter((c) => c.visible), [allColumns]);

  // Column visibility toggle
  function toggleColumn(key: string) {
    const newConfig: Record<string, boolean> = {};
    for (const col of allColumns) {
      newConfig[col.key] = col.key === key ? !col.visible : col.visible;
    }
    saveColumnConfig(spaceId, newConfig);
    setConfigVersion(v => v + 1);
  }

  // Client-side search filter
  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return items;
    const q = searchQuery.toLowerCase();
    return items.filter((item) => item.title.toLowerCase().includes(q));
  }, [items, searchQuery]);

  // Column sort handler
  function handleSort(field: string) {
    if (sortBy === field) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(field);
      setSortOrder('asc');
    }
  }

  // Update mutation
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
      {/* Table header bar */}
      <div className="px-4 py-2.5 border-b border-border flex items-center gap-3 shrink-0">
        <h3 className="text-sm font-semibold text-foreground">Table</h3>

        {/* Search */}
        <div className="relative">
          <input
            type="text"
            placeholder="Search..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-1.5 text-xs w-48 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent placeholder:text-muted"
          />
        </div>

        {/* Stage filter */}
        <select
          value={stageFilter}
          onChange={(e) => setStageFilter(e.target.value)}
          aria-label="Filter by stage"
          className="bg-raised text-foreground border border-border rounded-md px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
        >
          <option value="">All Stages</option>
          {boardColumns.map((col) => (
            <option key={col} value={col}>{col}</option>
          ))}
        </select>

        {/* Column config */}
        <div className="relative">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setColumnsPopoverOpen((v) => !v)}
          >
            Columns
          </Button>
          {columnsPopoverOpen && (
            <ColumnsPopover
              columns={allColumns}
              onToggle={toggleColumn}
              onClose={() => setColumnsPopoverOpen(false)}
            />
          )}
        </div>

        <div className="ml-auto">
          <Button size="sm" onClick={() => setCreateModalOpen(true)}>
            + New Record
          </Button>
        </div>
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-sm text-muted">Loading...</p>
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-sm text-muted">
            {searchQuery || stageFilter ? 'No matching records.' : 'No records yet.'}
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-raised z-10">
              <tr>
                {visibleColumns.map((col) => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key.startsWith('cf:') ? col.key : col.key)}
                    className="text-left px-3 py-2 text-xs font-semibold text-muted uppercase tracking-wider border-b border-border cursor-pointer hover:text-foreground select-none whitespace-nowrap"
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.label}
                      {sortBy === col.key && (
                        <span className="text-primary">{sortOrder === 'asc' ? '\u2191' : '\u2193'}</span>
                      )}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredItems.map((item) => (
                <TableRow
                  key={item.id}
                  item={item}
                  columns={visibleColumns}
                  boardColumns={boardColumns}
                  onRowClick={() => setSelectedItemId(item.id)}
                  onUpdate={(field, value) => {
                    if (field === 'stage') {
                      moveItem.mutate({
                        params: { path: { item_id: item.id } },
                        body: { stage: value as string },
                      });
                    } else if (field.startsWith('cf:')) {
                      const cfName = field.slice(3);
                      const existing = item.custom_fields ?? {};
                      updateItem.mutate({
                        params: { path: { item_id: item.id } },
                        body: {
                          custom_fields: { ...existing, [cfName]: value },
                        },
                      });
                    } else {
                      updateItem.mutate({
                        params: { path: { item_id: item.id } },
                        body: { [field]: value },
                      });
                    }
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreateRecordModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        spaceId={spaceId}
        boardColumns={boardColumns}
        fieldSchema={fieldSchema}
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

// --- Table Row ---

interface TableRowProps {
  item: ItemResponse;
  columns: ColumnDef[];
  boardColumns: string[];
  onRowClick: () => void;
  onUpdate: (field: string, value: unknown) => void;
}

function TableRow({ item, columns, boardColumns, onRowClick, onUpdate }: TableRowProps) {
  return (
    <tr
      className="border-b border-border/50 hover:bg-raised/50 cursor-pointer transition-colors"
      onClick={onRowClick}
    >
      {columns.map((col) => (
        <td key={col.key} className="px-3 py-2">
          <EditableCell
            column={col}
            item={item}
            boardColumns={boardColumns}
            onSave={(value) => onUpdate(col.key, value)}
          />
        </td>
      ))}
    </tr>
  );
}

// --- Editable Cell ---

interface EditableCellProps {
  column: ColumnDef;
  item: ItemResponse;
  boardColumns: string[];
  onSave: (value: unknown) => void;
}

function EditableCell({ column, item, boardColumns, onSave }: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement | HTMLSelectElement>(null);

  const rawValue = getCellValue(column, item);
  const displayValue = formatCellValue(column, rawValue);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
    }
  }, [editing]);

  const handleStartEdit = useCallback((e: React.MouseEvent) => {
    // Don't allow editing read-only columns
    if (column.key === 'created_at') return;
    e.stopPropagation();
    setEditing(true);
  }, [column.key]);

  const handleSave = useCallback((newValue: string) => {
    setEditing(false);
    let parsed: unknown = newValue;

    if (column.key === 'priority') {
      parsed = newValue ? Number(newValue) : null;
    } else if (column.key === 'due_date' || column.fieldType === 'date') {
      parsed = newValue ? `${newValue}T00:00:00` : null;
    } else if (column.fieldType === 'number') {
      parsed = newValue ? Number(newValue) : null;
    } else if (!newValue && column.key !== 'title') {
      parsed = null;
    }

    // Don't save if value didn't change
    const currentRaw = getCellValue(column, item);
    if (String(parsed ?? '') === String(currentRaw ?? '')) return;

    onSave(parsed);
  }, [column, item, onSave]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      (e.target as HTMLInputElement).blur();
    } else if (e.key === 'Escape') {
      setEditing(false);
    }
  }, []);

  // Read-only columns
  if (column.key === 'created_at') {
    return <span className="text-xs text-muted">{displayValue}</span>;
  }

  if (editing) {
    // Stage uses a select
    if (column.key === 'stage') {
      return (
        <select
          ref={inputRef as React.RefObject<HTMLSelectElement>}
          defaultValue={String(rawValue ?? '')}
          onBlur={(e) => handleSave(e.target.value)}
          onChange={(e) => handleSave(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          aria-label="Stage"
          className="bg-raised text-foreground border border-primary rounded px-1.5 py-0.5 text-xs w-full focus:outline-none"
        >
          {boardColumns.map((col) => (
            <option key={col} value={col}>{col}</option>
          ))}
        </select>
      );
    }

    // Select type custom fields
    if (column.fieldType === 'select' && column.options) {
      return (
        <select
          ref={inputRef as React.RefObject<HTMLSelectElement>}
          defaultValue={String(rawValue ?? '')}
          onBlur={(e) => handleSave(e.target.value)}
          onChange={(e) => handleSave(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          aria-label={column.label}
          className="bg-raised text-foreground border border-primary rounded px-1.5 py-0.5 text-xs w-full focus:outline-none"
        >
          <option value="">--</option>
          {column.options.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      );
    }

    // Date inputs
    if (column.key === 'due_date' || column.fieldType === 'date') {
      const dateVal = rawValue ? String(rawValue).slice(0, 10) : '';
      return (
        <input
          ref={inputRef as React.RefObject<HTMLInputElement>}
          type="date"
          defaultValue={dateVal}
          onBlur={(e) => handleSave(e.target.value)}
          onKeyDown={handleKeyDown}
          onClick={(e) => e.stopPropagation()}
          className="bg-raised text-foreground border border-primary rounded px-1.5 py-0.5 text-xs w-full focus:outline-none"
        />
      );
    }

    // Number inputs
    if (column.key === 'priority' || column.fieldType === 'number') {
      return (
        <input
          ref={inputRef as React.RefObject<HTMLInputElement>}
          type="number"
          defaultValue={rawValue != null ? String(rawValue) : ''}
          onBlur={(e) => handleSave(e.target.value)}
          onKeyDown={handleKeyDown}
          onClick={(e) => e.stopPropagation()}
          className="bg-raised text-foreground border border-primary rounded px-1.5 py-0.5 text-xs w-full focus:outline-none"
        />
      );
    }

    // Default text input
    return (
      <input
        ref={inputRef as React.RefObject<HTMLInputElement>}
        type="text"
        defaultValue={String(rawValue ?? '')}
        onBlur={(e) => handleSave(e.target.value)}
        onKeyDown={handleKeyDown}
        onClick={(e) => e.stopPropagation()}
        className="bg-raised text-foreground border border-primary rounded px-1.5 py-0.5 text-xs w-full focus:outline-none"
      />
    );
  }

  // Display mode
  return (
    <span
      className="text-xs text-foreground cursor-text hover:bg-raised/80 rounded px-1 -mx-1 py-0.5 inline-block min-w-[2rem]"
      onClick={handleStartEdit}
    >
      {displayValue || <span className="text-muted">--</span>}
    </span>
  );
}

// --- Helpers ---

function getCellValue(column: ColumnDef, item: ItemResponse): unknown {
  if (column.type === 'custom') {
    const cfName = column.key.slice(3); // strip "cf:"
    return item.custom_fields?.[cfName] ?? null;
  }
  switch (column.key) {
    case 'title': return item.title;
    case 'stage': return item.stage;
    case 'priority': return item.priority;
    case 'due_date': return item.due_date;
    case 'created_at': return item.created_at;
    default: return null;
  }
}

function formatCellValue(column: ColumnDef, value: unknown): string {
  if (value == null) return '';
  if (column.key === 'created_at' || column.key === 'due_date' || column.fieldType === 'date') {
    try {
      return new Date(String(value)).toLocaleDateString();
    } catch {
      return String(value);
    }
  }
  return String(value);
}

// --- Columns Popover ---

interface ColumnsPopoverProps {
  columns: ColumnDef[];
  onToggle: (key: string) => void;
  onClose: () => void;
}

function ColumnsPopover({ columns, onToggle, onClose }: ColumnsPopoverProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="absolute top-full left-0 mt-1 bg-surface border border-border rounded-lg shadow-lg p-3 z-50 min-w-[180px]"
    >
      <p className="text-xs font-semibold text-muted uppercase tracking-wider mb-2">Show Columns</p>
      {columns.map((col) => (
        <label key={col.key} className="flex items-center gap-2 py-1 cursor-pointer">
          <input
            type="checkbox"
            checked={col.visible}
            onChange={() => onToggle(col.key)}
            className="rounded border-border"
          />
          <span className="text-xs text-foreground">{col.label}</span>
        </label>
      ))}
    </div>
  );
}
