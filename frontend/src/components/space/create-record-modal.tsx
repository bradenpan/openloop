import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Modal, Button, Input } from '../ui';

interface FieldSchema {
  name: string;
  type: string;
  options?: string[];
}

interface CreateRecordModalProps {
  open: boolean;
  onClose: () => void;
  spaceId: string;
  boardColumns: string[];
  fieldSchema: FieldSchema[];
}

export function CreateRecordModal({
  open,
  onClose,
  spaceId,
  boardColumns,
  fieldSchema,
}: CreateRecordModalProps) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [stage, setStage] = useState(boardColumns[0] ?? '');
  const [dueDate, setDueDate] = useState('');
  const [customFields, setCustomFields] = useState<Record<string, string>>({});

  const createItem = $api.useMutation('post', '/api/v1/items', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
      resetAndClose();
    },
  });

  function resetAndClose() {
    setTitle('');
    setStage(boardColumns[0] ?? '');
    setDueDate('');
    setCustomFields({});
    onClose();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;

    // Build custom_fields object, only include non-empty values
    const cf: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(customFields)) {
      if (val.trim()) {
        // Find the field schema to determine type
        const schema = fieldSchema.find((f) => f.name === key);
        if (schema?.type === 'number') {
          cf[key] = Number(val);
        } else {
          cf[key] = val;
        }
      }
    }

    createItem.mutate({
      body: {
        space_id: spaceId,
        title: title.trim(),
        item_type: 'task',
        stage,
        due_date: dueDate ? `${dueDate}T00:00:00` : null,
        custom_fields: Object.keys(cf).length > 0 ? cf : null,
        is_agent_task: false,
      },
    });
  }

  return (
    <Modal open={open} onClose={resetAndClose} title="New Record">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input
          label="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Record title"
          required
          autoFocus
        />

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Stage</label>
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value)}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          >
            {boardColumns.map((col) => (
              <option key={col} value={col}>{col}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Due Date</label>
          <input
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          />
        </div>

        {/* Custom fields from schema */}
        {fieldSchema.map((field) => (
          <div key={field.name} className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-foreground capitalize">
              {field.name.replace(/_/g, ' ')}
            </label>
            {field.type === 'select' && field.options ? (
              <select
                value={customFields[field.name] ?? ''}
                onChange={(e) =>
                  setCustomFields((prev) => ({ ...prev, [field.name]: e.target.value }))
                }
                className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              >
                <option value="">--</option>
                {field.options.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            ) : (
              <input
                type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
                value={customFields[field.name] ?? ''}
                onChange={(e) =>
                  setCustomFields((prev) => ({ ...prev, [field.name]: e.target.value }))
                }
                placeholder={field.name.replace(/_/g, ' ')}
                className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
              />
            )}
          </div>
        ))}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={resetAndClose}>
            Cancel
          </Button>
          <Button type="submit" loading={createItem.isPending} disabled={!title.trim()}>
            Create Record
          </Button>
        </div>
      </form>
    </Modal>
  );
}
