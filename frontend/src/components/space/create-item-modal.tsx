import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Modal, Button, Input } from '../ui';

interface CreateItemModalProps {
  open: boolean;
  onClose: () => void;
  spaceId: string;
  boardColumns: string[];
}

export function CreateItemModal({ open, onClose, spaceId, boardColumns }: CreateItemModalProps) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [itemType, setItemType] = useState<'task' | 'record'>('task');
  const [stage, setStage] = useState(boardColumns[0] ?? '');
  const [description, setDescription] = useState('');

  const createItem = $api.useMutation('post', '/api/v1/items', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/items'] });
      resetAndClose();
    },
  });

  function resetAndClose() {
    setTitle('');
    setItemType('task');
    setStage(boardColumns[0] ?? '');
    setDescription('');
    onClose();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    createItem.mutate({
      body: {
        space_id: spaceId,
        title: title.trim(),
        item_type: itemType,
        stage,
        description: description.trim() || null,
        is_agent_task: false,
      },
    });
  }

  return (
    <Modal open={open} onClose={resetAndClose} title="Create Item">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input
          label="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Item title"
          required
          autoFocus
        />

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Type</label>
          <select
            value={itemType}
            onChange={(e) => setItemType(e.target.value as 'task' | 'record')}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          >
            <option value="task">Task</option>
            <option value="record">Record</option>
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Stage</label>
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value)}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          >
            {boardColumns.map((col) => (
              <option key={col} value={col}>
                {col}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
            rows={3}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent resize-none"
          />
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={resetAndClose}>
            Cancel
          </Button>
          <Button type="submit" loading={createItem.isPending} disabled={!title.trim()}>
            Create
          </Button>
        </div>
      </form>
    </Modal>
  );
}
