import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import type { components } from '../../api/types';
import { Modal, Button, Input } from '../ui';

type SpaceTemplate = components['schemas']['SpaceTemplate'];

interface CreateSpaceModalProps {
  open: boolean;
  onClose: () => void;
}

const TEMPLATES: { value: SpaceTemplate; label: string; description: string }[] = [
  { value: 'project', label: 'Project', description: 'Task board with stages and items' },
  { value: 'crm', label: 'Database', description: 'Structured data and records' },
  { value: 'knowledge_base', label: 'Knowledge Base', description: 'Documents and reference material' },
  { value: 'simple', label: 'Simple', description: 'Lightweight space for notes and conversations' },
];

export function CreateSpaceModal({ open, onClose }: CreateSpaceModalProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [template, setTemplate] = useState<SpaceTemplate>('project');
  const [description, setDescription] = useState('');

  const createSpace = $api.useMutation('post', '/api/v1/spaces', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/spaces'] });
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/home/dashboard'] });
      resetAndClose();
    },
  });

  function resetAndClose() {
    setName('');
    setTemplate('project');
    setDescription('');
    onClose();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    createSpace.mutate({
      body: {
        name: name.trim(),
        template,
        description: description.trim() || null,
      },
    });
  }

  return (
    <Modal open={open} onClose={resetAndClose} title="Create Space">
      <form onSubmit={handleSubmit} className="space-y-5">
        <Input
          label="Space Name"
          placeholder="e.g. Q2 Launch"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          required
        />

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Template</label>
          <div className="grid grid-cols-2 gap-2">
            {TEMPLATES.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setTemplate(t.value)}
                className={`text-left px-3 py-2.5 rounded-lg border transition-colors duration-150 cursor-pointer ${
                  template === t.value
                    ? 'border-primary bg-primary/10 text-foreground'
                    : 'border-border bg-raised text-muted hover:text-foreground hover:border-foreground/20'
                }`}
              >
                <span className="block text-sm font-medium">{t.label}</span>
                <span className="block text-xs text-muted mt-0.5">{t.description}</span>
              </button>
            ))}
          </div>
        </div>

        <Input
          label="Description (optional)"
          placeholder="What is this space for?"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={resetAndClose}>
            Cancel
          </Button>
          <Button type="submit" loading={createSpace.isPending} disabled={!name.trim()}>
            Create Space
          </Button>
        </div>
      </form>
    </Modal>
  );
}
