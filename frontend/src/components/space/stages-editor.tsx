import { useEffect, useState, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button } from '../ui';

interface StageEntry {
  id: string;
  name: string;
}

function toEntries(names: string[]): StageEntry[] {
  return names.map((name) => ({ id: crypto.randomUUID(), name }));
}

interface StagesEditorProps {
  spaceId: string;
}

export function StagesEditor({ spaceId }: StagesEditorProps) {
  const queryClient = useQueryClient();

  const { data: space } = $api.useQuery('get', '/api/v1/spaces/{space_id}', {
    params: { path: { space_id: spaceId } },
  });

  const [columns, setColumns] = useState<StageEntry[]>([]);
  const [original, setOriginal] = useState<string[]>([]);

  // Sync local state when space data loads or changes
  useEffect(() => {
    if (space) {
      const cols = space.board_columns ?? [];
      setColumns(toEntries(cols));
      setOriginal([...cols]);
    }
  }, [space?.board_columns]);

  const updateSpace = $api.useMutation('patch', '/api/v1/spaces/{space_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces/{space_id}'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces'] });
    },
  });

  // --- Derived values for validation ---

  const names = columns.map((c) => c.name);
  const hasEmpty = names.some((n) => n.trim() === '');
  const lowerNames = names.map((n) => n.trim().toLowerCase());
  const hasDuplicates = lowerNames.length !== new Set(lowerNames).size;
  const tooFew = columns.length < 1;
  const isDirty = JSON.stringify(names) !== JSON.stringify(original);
  const isValid = !hasEmpty && !hasDuplicates && !tooFew;
  const canSave = isDirty && isValid && !updateSpace.isPending;

  // --- Handlers ---

  const handleRename = useCallback((index: number, value: string) => {
    setColumns((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], name: value };
      return next;
    });
  }, []);

  const handleMoveUp = useCallback((index: number) => {
    if (index === 0) return;
    setColumns((prev) => {
      const next = [...prev];
      [next[index - 1], next[index]] = [next[index], next[index - 1]];
      return next;
    });
  }, []);

  const handleMoveDown = useCallback((index: number) => {
    setColumns((prev) => {
      if (index >= prev.length - 1) return prev;
      const next = [...prev];
      [next[index], next[index + 1]] = [next[index + 1], next[index]];
      return next;
    });
  }, []);

  const handleRemove = useCallback((index: number) => {
    setColumns((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleAdd = useCallback(() => {
    setColumns((prev) => [...prev, { id: crypto.randomUUID(), name: '' }]);
  }, []);

  const handleSave = () => {
    if (!canSave) return;
    updateSpace.mutate({
      params: { path: { space_id: spaceId } },
      body: { board_columns: names.map((n) => n.trim()) },
    });
  };

  // --- Validation messages ---

  let validationMsg: string | null = null;
  if (hasEmpty) validationMsg = 'Stage names cannot be empty.';
  else if (hasDuplicates) validationMsg = 'Stage names must be unique.';
  else if (tooFew) validationMsg = 'At least one stage is required.';

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground mb-1">Stages</h3>
        <p className="text-xs text-muted">
          Configure the columns/stages for your board and table views.
        </p>
      </div>

      {/* Stage list */}
      <div className="flex flex-col gap-1.5">
        {columns.map((col, idx) => (
          <div key={col.id} className="flex items-center gap-1.5">
            {/* Name input */}
            <input
              type="text"
              value={col.name}
              onChange={(e) => handleRename(idx, e.target.value)}
              placeholder="Stage name"
              className={`flex-1 min-w-0 px-2.5 py-1.5 text-sm rounded-md border bg-surface text-foreground placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-primary transition-colors ${
                col.name.trim() === '' || (lowerNames.filter((n) => n === col.name.trim().toLowerCase()).length > 1 && col.name.trim() !== '')
                  ? 'border-destructive'
                  : 'border-border'
              }`}
            />

            {/* Move up */}
            <button
              onClick={() => handleMoveUp(idx)}
              disabled={idx === 0}
              className="text-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed p-1 rounded hover:bg-raised transition-colors cursor-pointer"
              aria-label="Move up"
              title="Move up"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M7 11V3M3.5 6.5L7 3l3.5 3.5" />
              </svg>
            </button>

            {/* Move down */}
            <button
              onClick={() => handleMoveDown(idx)}
              disabled={idx >= columns.length - 1}
              className="text-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed p-1 rounded hover:bg-raised transition-colors cursor-pointer"
              aria-label="Move down"
              title="Move down"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M7 3v8M3.5 7.5L7 11l3.5-3.5" />
              </svg>
            </button>

            {/* Remove */}
            <button
              onClick={() => handleRemove(idx)}
              disabled={columns.length <= 1}
              className="text-muted hover:text-destructive disabled:opacity-30 disabled:cursor-not-allowed p-1 rounded hover:bg-destructive/10 transition-colors cursor-pointer"
              aria-label="Remove stage"
              title="Remove"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
              </svg>
            </button>
          </div>
        ))}
      </div>

      {/* Add stage */}
      <Button
        variant="secondary"
        size="sm"
        onClick={handleAdd}
        className="self-stretch"
      >
        <span className="mr-1">+</span> Add Stage
      </Button>

      {/* Validation message */}
      {validationMsg && isDirty && (
        <p className="text-xs text-destructive">{validationMsg}</p>
      )}

      {/* Save */}
      <Button
        variant="primary"
        size="sm"
        disabled={!canSave}
        onClick={handleSave}
        className="self-stretch"
      >
        {updateSpace.isPending ? 'Saving...' : 'Save Changes'}
      </Button>
    </div>
  );
}
