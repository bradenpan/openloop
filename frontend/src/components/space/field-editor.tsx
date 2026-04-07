import { useEffect, useState, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button } from '../ui';

const FIELD_TYPES = ['text', 'number', 'date', 'select'] as const;
type FieldType = (typeof FIELD_TYPES)[number];

interface FieldDef {
  _key: string; // Stable React key — not sent to server
  name: string;
  type: FieldType;
  options?: string[];
  optionsRaw?: string;
}

interface FieldEditorProps {
  spaceId: string;
}

export function FieldEditor({ spaceId }: FieldEditorProps) {
  const queryClient = useQueryClient();

  const { data: fieldSchemaData } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}/field-schema',
    { params: { path: { space_id: spaceId } } },
  );

  const [fields, setFields] = useState<FieldDef[]>([]);
  const [original, setOriginal] = useState<FieldDef[]>([]);

  // Sync local state when server data loads
  useEffect(() => {
    if (Array.isArray(fieldSchemaData)) {
      const parsed: FieldDef[] = (fieldSchemaData as FieldDef[]).map((f) => ({
        _key: crypto.randomUUID(),
        name: f.name ?? '',
        type: (FIELD_TYPES.includes(f.type as FieldType) ? f.type : 'text') as FieldType,
        options: f.options,
        optionsRaw: (f.options ?? []).join(', '),
      }));
      setFields(parsed);
      setOriginal(parsed);
    }
  }, [fieldSchemaData]);

  const updateSpace = $api.useMutation('patch', '/api/v1/spaces/{space_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces/{space_id}'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces/{space_id}/field-schema'] });
    },
  });

  // --- Validation ---

  const hasEmpty = fields.some((f) => f.name.trim() === '');
  const lowerNames = fields.map((f) => f.name.trim().toLowerCase());
  const hasDuplicates = lowerNames.length !== new Set(lowerNames).size;
  const isDirty = JSON.stringify(fields) !== JSON.stringify(original);
  const isValid = !hasEmpty && !hasDuplicates;
  const canSave = isDirty && isValid && !updateSpace.isPending;

  // --- Handlers ---

  const handleNameChange = useCallback((index: number, value: string) => {
    setFields((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], name: value };
      return next;
    });
  }, []);

  const handleTypeChange = useCallback((index: number, value: FieldType) => {
    setFields((prev) => {
      const next = [...prev];
      const field = { ...next[index], type: value };
      // Initialize options when switching to select (if none exist yet)
      if (value === 'select' && !field.options) {
        field.options = [];
        field.optionsRaw = '';
      }
      // Keep options in state when switching away — just hide the UI
      next[index] = field;
      return next;
    });
  }, []);

  const handleOptionsChange = useCallback((index: number, value: string) => {
    setFields((prev) => {
      const next = [...prev];
      next[index] = {
        ...next[index],
        optionsRaw: value,
        options: value.split(',').map((o) => o.trim()),
      };
      return next;
    });
  }, []);

  const handleRemove = useCallback((index: number) => {
    setFields((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleAdd = useCallback(() => {
    setFields((prev) => [...prev, { _key: crypto.randomUUID(), name: '', type: 'text' }]);
  }, []);

  const handleSave = () => {
    if (!canSave) return;
    const cleaned = fields.map((f) => {
      const out: { name: string; type: FieldType; options?: string[] } = { name: f.name.trim(), type: f.type };
      if (f.type === 'select' && f.options) {
        const filtered = f.options.filter(Boolean);
        if (filtered.length > 0) {
          out.options = filtered;
        }
      }
      return out;
    });
    updateSpace.mutate({
      params: { path: { space_id: spaceId } },
      body: { custom_field_schema: cleaned as unknown as Record<string, never>[] },
    });
  };

  // --- Validation messages ---

  let validationMsg: string | null = null;
  if (hasEmpty) validationMsg = 'Field names cannot be empty.';
  else if (hasDuplicates) validationMsg = 'Field names must be unique.';

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground mb-1">Custom Fields</h3>
        <p className="text-xs text-muted">
          Define additional fields for records in this space.
        </p>
      </div>

      {/* Field list */}
      <div className="flex flex-col gap-2">
        {fields.map((field, idx) => (
          <div key={field._key} className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5">
              {/* Name input */}
              <input
                type="text"
                value={field.name}
                onChange={(e) => handleNameChange(idx, e.target.value)}
                placeholder="Field name"
                className={`flex-1 min-w-0 px-2.5 py-1.5 text-sm rounded-md border bg-surface text-foreground placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-primary transition-colors ${
                  field.name.trim() === '' ||
                  (lowerNames.filter((n) => n === field.name.trim().toLowerCase()).length > 1 && field.name.trim() !== '')
                    ? 'border-destructive'
                    : 'border-border'
                }`}
              />

              {/* Type selector */}
              <select
                value={field.type}
                onChange={(e) => handleTypeChange(idx, e.target.value as FieldType)}
                className="px-2 py-1.5 text-sm rounded-md border border-border bg-surface text-foreground focus:outline-none focus:ring-1 focus:ring-primary transition-colors cursor-pointer"
                aria-label="Field type"
              >
                {FIELD_TYPES.map((ft) => (
                  <option key={ft} value={ft}>
                    {ft.charAt(0).toUpperCase() + ft.slice(1)}
                  </option>
                ))}
              </select>

              {/* Remove button */}
              <button
                onClick={() => handleRemove(idx)}
                className="text-muted hover:text-destructive p-1 rounded hover:bg-destructive/10 transition-colors cursor-pointer"
                aria-label="Remove field"
                title="Remove"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
                </svg>
              </button>
            </div>

            {/* Options input for select type */}
            {field.type === 'select' && (
              <input
                type="text"
                value={field.optionsRaw ?? ''}
                onChange={(e) => handleOptionsChange(idx, e.target.value)}
                placeholder="Options (comma-separated)"
                className="ml-0 px-2.5 py-1.5 text-sm rounded-md border border-border bg-surface text-foreground placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-primary transition-colors"
              />
            )}
          </div>
        ))}
      </div>

      {/* Add field */}
      <Button
        variant="secondary"
        size="sm"
        onClick={handleAdd}
        className="self-stretch"
      >
        <span className="mr-1">+</span> Add Field
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
