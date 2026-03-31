import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Panel, Button, Badge } from '../ui';
import type { components } from '../../api/types';

type ItemResponse = components['schemas']['ItemResponse'];
type TodoResponse = components['schemas']['TodoResponse'];

interface FieldSchema {
  name: string;
  type: string;
  options?: string[];
}

interface ItemDetailPanelProps {
  itemId: string | null;
  open: boolean;
  onClose: () => void;
  boardColumns: string[];
}

export function ItemDetailPanel({ itemId, open, onClose, boardColumns }: ItemDetailPanelProps) {
  const queryClient = useQueryClient();

  const { data: itemData } = $api.useQuery(
    'get',
    '/api/v1/items/{item_id}',
    { params: { path: { item_id: itemId! } } },
    { enabled: open && itemId != null },
  );
  const item = itemData;

  const { data: eventsData } = $api.useQuery(
    'get',
    '/api/v1/items/{item_id}/events',
    { params: { path: { item_id: itemId! } } },
    { enabled: open && itemId != null },
  );
  const events = eventsData ?? [];

  // Fetch children (child records + linked todos)
  const { data: childrenData } = $api.useQuery(
    'get',
    '/api/v1/items/{item_id}/children',
    { params: { path: { item_id: itemId! } } },
    { enabled: open && itemId != null },
  );
  const childRecords: ItemResponse[] = childrenData?.child_records ?? [];
  const linkedTodos: TodoResponse[] = childrenData?.linked_todos ?? [];

  // Fetch field schema from the item's space
  const spaceIdForSchema = itemData?.space_id;
  const { data: fieldSchemaData } = $api.useQuery(
    'get',
    '/api/v1/spaces/{space_id}/field-schema',
    { params: { path: { space_id: spaceIdForSchema! } } },
    { enabled: open && spaceIdForSchema != null },
  );
  const fieldSchema: FieldSchema[] = Array.isArray(fieldSchemaData) ? fieldSchemaData as FieldSchema[] : [];

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [stage, setStage] = useState('');
  const [priority, setPriority] = useState<string>('');
  const [dueDate, setDueDate] = useState('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (item) {
      setTitle(item.title);
      setDescription(item.description ?? '');
      setStage(item.stage ?? '');
      setPriority(item.priority != null ? String(item.priority) : '');
      setDueDate(item.due_date ? item.due_date.slice(0, 10) : '');
      setDirty(false);
    }
  }, [item]);

  const updateItem = $api.useMutation('patch', '/api/v1/items/{item_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
      queryClient.invalidateQueries({
        queryKey: ['get', '/api/v1/items/{item_id}', { params: { path: { item_id: itemId! } } }],
      });
      setDirty(false);
    },
  });

  function handleSave() {
    if (!itemId || !item) return;
    updateItem.mutate({
      params: { path: { item_id: itemId } },
      body: {
        title: title !== item.title ? title : undefined,
        description: description !== (item.description ?? '') ? description || null : undefined,
        priority: priority !== (item.priority != null ? String(item.priority) : '')
          ? (priority ? Number(priority) : null)
          : undefined,
        due_date: dueDate !== (item.due_date ? item.due_date.slice(0, 10) : '')
          ? (dueDate ? `${dueDate}T00:00:00` : null)
          : undefined,
      },
    });
    // Stage change uses move endpoint
    if (stage !== (item.stage ?? '')) {
      moveItem.mutate({
        params: { path: { item_id: itemId } },
        body: { stage },
      });
    }
  }

  const moveItem = $api.useMutation('post', '/api/v1/items/{item_id}/move', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
    },
  });

  function markDirty() {
    setDirty(true);
  }

  if (!open || !itemId) return null;

  return (
    <Panel open={open} onClose={onClose} title="Item Details" width="480px">
      {!item ? (
        <p className="text-sm text-muted">Loading...</p>
      ) : (
        <div className="flex flex-col gap-5">
          {/* Title */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted uppercase tracking-wider">Title</label>
            <input
              value={title}
              onChange={(e) => { setTitle(e.target.value); markDirty(); }}
              className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
            />
          </div>

          {/* Description */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted uppercase tracking-wider">Description</label>
            <textarea
              value={description}
              onChange={(e) => { setDescription(e.target.value); markDirty(); }}
              rows={4}
              className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent resize-none"
              placeholder="No description"
            />
          </div>

          {/* Stage */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted uppercase tracking-wider">Stage</label>
            <select
              value={stage}
              onChange={(e) => { setStage(e.target.value); markDirty(); }}
              className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
            >
              {boardColumns.map((col) => (
                <option key={col} value={col}>{col}</option>
              ))}
            </select>
          </div>

          {/* Priority + Due Date row */}
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted uppercase tracking-wider">Priority</label>
              <input
                type="number"
                min={0}
                max={5}
                value={priority}
                onChange={(e) => { setPriority(e.target.value); markDirty(); }}
                placeholder="--"
                className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted uppercase tracking-wider">Due Date</label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => { setDueDate(e.target.value); markDirty(); }}
                className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              />
            </div>
          </div>

          {/* Custom Fields */}
          {fieldSchema.length > 0 && item.custom_fields && (
            <div className="border-t border-border pt-4 mt-1">
              <h4 className="text-xs font-medium text-muted uppercase tracking-wider mb-3">Custom Fields</h4>
              <div className="flex flex-col gap-2">
                {fieldSchema.map((field) => {
                  const val = item.custom_fields?.[field.name];
                  return (
                    <div key={field.name} className="flex items-center gap-2">
                      <span className="text-xs text-muted w-28 shrink-0 capitalize">{field.name.replace(/_/g, ' ')}</span>
                      <span className="text-xs text-foreground">{val != null ? String(val) : '--'}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Child Records */}
          {childRecords.length > 0 && (
            <div className="border-t border-border pt-4 mt-1">
              <h4 className="text-xs font-medium text-muted uppercase tracking-wider mb-3">Child Records</h4>
              <div className="flex flex-col gap-1.5">
                {childRecords.map((child) => (
                  <div key={child.id} className="flex items-center gap-2 text-xs bg-raised rounded-md px-3 py-2">
                    <span className="text-foreground font-medium flex-1 truncate">{child.title}</span>
                    {child.stage && <Badge variant="info">{child.stage}</Badge>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Linked Todos */}
          {linkedTodos.length > 0 && (
            <div className="border-t border-border pt-4 mt-1">
              <h4 className="text-xs font-medium text-muted uppercase tracking-wider mb-3">Linked Todos</h4>
              <div className="flex flex-col gap-1.5">
                {linkedTodos.map((todo) => (
                  <div key={todo.id} className="flex items-center gap-2 text-xs bg-raised rounded-md px-3 py-2">
                    <span className={`flex-1 truncate ${todo.is_done ? 'line-through text-muted' : 'text-foreground'}`}>
                      {todo.title}
                    </span>
                    {todo.is_done && <Badge variant="success">Done</Badge>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Metadata */}
          <div className="flex items-center gap-2 text-xs text-muted">
            <Badge variant={item.item_type === 'task' ? 'default' : 'info'}>{item.item_type}</Badge>
            <span>Created {new Date(item.created_at).toLocaleDateString()}</span>
            {item.archived && <Badge variant="warning">Archived</Badge>}
          </div>

          {/* Save button */}
          <Button
            onClick={handleSave}
            disabled={!dirty}
            loading={updateItem.isPending || moveItem.isPending}
            className="self-end"
          >
            Save Changes
          </Button>

          {/* Events history */}
          {events.length > 0 && (
            <div className="border-t border-border pt-4 mt-1">
              <h4 className="text-xs font-medium text-muted uppercase tracking-wider mb-3">History</h4>
              <div className="flex flex-col gap-2 max-h-48 overflow-auto">
                {events.map((evt) => (
                  <div key={evt.id} className="text-xs text-muted flex items-start gap-2">
                    <span className="shrink-0 text-foreground font-medium">{evt.event_type}</span>
                    <span className="truncate">
                      {evt.old_value && <span className="line-through mr-1">{evt.old_value}</span>}
                      {evt.new_value && <span>{evt.new_value}</span>}
                    </span>
                    <span className="shrink-0 ml-auto">
                      {new Date(evt.created_at).toLocaleDateString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
