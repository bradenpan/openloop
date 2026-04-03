import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { api } from '../../api/client';
import type { components } from '../../api/types';
import { useToastStore } from '../../stores/toast-store';
import { Modal } from '../ui';
import { Input } from '../ui';
import { Button } from '../ui';

type Agent = components['schemas']['AgentResponse'];

const MODELS = ['haiku', 'sonnet', 'opus'] as const;
const SPAWN_DEPTH_OPTIONS = [1, 2, 3, 4, 5] as const;

interface AgentFormModalProps {
  open: boolean;
  onClose: () => void;
  agent?: Agent | null;
}

export function AgentFormModal({ open, onClose, agent }: AgentFormModalProps) {
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isEditing = !!agent;

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [defaultModel, setDefaultModel] = useState<string>('sonnet');
  const [maxSpawnDepth, setMaxSpawnDepth] = useState<number>(1);

  useEffect(() => {
    if (open) {
      if (agent) {
        setName(agent.name);
        setDescription(agent.description ?? '');
        setSystemPrompt(agent.system_prompt ?? '');
        setDefaultModel(agent.default_model);
        setMaxSpawnDepth(agent.max_spawn_depth ?? 1);
      } else {
        setName('');
        setDescription('');
        setSystemPrompt('');
        setDefaultModel('sonnet');
        setMaxSpawnDepth(1);
      }
    }
  }, [open, agent]);

  const createAgent = $api.useMutation('post', '/api/v1/agents', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents'] });
      onClose();
    },
  });

  const updateAgent = $api.useMutation('patch', '/api/v1/agents/{agent_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents'] });
      onClose();
    },
  });

  const isPending = createAgent.isPending || updateAgent.isPending;
  const error = createAgent.error || updateAgent.error;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    if (isEditing && agent) {
      updateAgent.mutate({
        params: { path: { agent_id: agent.id } },
        body: {
          name: name.trim(),
          description: description.trim() || null,
          system_prompt: systemPrompt.trim() || null,
          default_model: defaultModel,
          max_spawn_depth: maxSpawnDepth,
        },
      });
    } else {
      createAgent.mutate({
        body: {
          name: name.trim(),
          description: description.trim() || null,
          system_prompt: systemPrompt.trim() || null,
          default_model: defaultModel,
        },
      }, {
        onSuccess: async (created) => {
          // AgentCreate doesn't include max_spawn_depth, so if the user
          // set a non-default value, follow up with a PATCH.
          if (maxSpawnDepth !== 1 && created.id) {
            try {
              await api.PATCH('/api/v1/agents/{agent_id}', {
                params: { path: { agent_id: created.id } },
                body: { max_spawn_depth: maxSpawnDepth },
              });
            } catch {
              addToast('Agent created but failed to set delegation depth.', 'warning');
            }
          }
          queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents'] });
        },
      });
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={isEditing ? 'Edit Agent' : 'New Agent'}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Research Assistant"
          required
        />

        <Input
          label="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Optional description"
        />

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">System Prompt</label>
          <textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Instructions for the agent..."
            rows={5}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150 resize-y"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Default Model</label>
          <select
            value={defaultModel}
            onChange={(e) => setDefaultModel(e.target.value)}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150 cursor-pointer"
          >
            {MODELS.map((m) => (
              <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Max Delegation Depth</label>
          <select
            value={maxSpawnDepth}
            onChange={(e) => setMaxSpawnDepth(Number(e.target.value))}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150 cursor-pointer"
          >
            {SPAWN_DEPTH_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} {n === 1 ? '(no nesting)' : n === 2 ? '(1 level of sub-agents)' : `(${n - 1} levels of sub-agents)`}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted">
            Controls how many levels of sub-agent delegation this agent can create.
            Level 1 means sub-agents cannot delegate further.
          </p>
        </div>

        {error && (
          <p className="text-sm text-destructive">
            {error instanceof Error ? error.message : 'An error occurred'}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isPending}>
            Cancel
          </Button>
          <Button type="submit" loading={isPending} disabled={!name.trim()}>
            {isEditing ? 'Save Changes' : 'Create Agent'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
