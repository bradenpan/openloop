import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Modal, Button, Input } from '../ui';

interface NewConversationModalProps {
  open: boolean;
  onClose: () => void;
  spaceId: string;
}

const MODEL_OPTIONS = [
  { value: '', label: 'Agent default' },
  { value: 'sonnet', label: 'Sonnet' },
  { value: 'opus', label: 'Opus' },
  { value: 'haiku', label: 'Haiku' },
];

const MODEL_DESCRIPTIONS: Record<string, string> = {
  '': "Uses the agent's configured model (usually Sonnet). Right for most work.",
  sonnet:
    "Best for most work \u2014 domain conversations, task management, research, content. Handles 80% of what you'll ask. Not ideal when getting it wrong on the first try is costly.",
  opus:
    "Best for complex work \u2014 planning across multiple spaces, deep research, architecture decisions, autonomous goals. Thinks deeper, gets complex things right the first time. Slower, ~1.7\u00d7 Sonnet's usage cost.",
  haiku:
    "Best for quick questions \u2014 'what's on my plate today?', status checks, simple lookups. Fast, light on usage. Not for anything requiring judgment or multi-step reasoning.",
};

export function NewConversationModal({ open, onClose, spaceId }: NewConversationModalProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [agentId, setAgentId] = useState('');
  const [modelOverride, setModelOverride] = useState('');

  const { data: agentsData } = $api.useQuery('get', '/api/v1/agents', {}, { enabled: open });
  const agents = agentsData ?? [];

  const createConversation = $api.useMutation('post', '/api/v1/conversations', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/conversations'] });
      resetAndClose();
    },
  });

  function resetAndClose() {
    setName('');
    setAgentId('');
    setModelOverride('');
    onClose();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !agentId) return;
    createConversation.mutate({
      body: {
        agent_id: agentId,
        name: name.trim(),
        space_id: spaceId,
        model_override: modelOverride || null,
      },
    });
  }

  return (
    <Modal open={open} onClose={resetAndClose} title="New Conversation">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Input
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Conversation name"
          required
          autoFocus
        />

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Agent</label>
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            required
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          >
            <option value="" disabled>
              Select an agent
            </option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
          {agents.length === 0 && (
            <p className="text-xs text-muted">No agents available. Create one in Settings first.</p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">Model</label>
          <select
            value={modelOverride}
            onChange={(e) => setModelOverride(e.target.value)}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          >
            {MODEL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          {MODEL_DESCRIPTIONS[modelOverride] && (
            <p className="text-xs text-muted mt-1">{MODEL_DESCRIPTIONS[modelOverride]}</p>
          )}
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={resetAndClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            loading={createConversation.isPending}
            disabled={!name.trim() || !agentId}
          >
            Create
          </Button>
        </div>
      </form>
    </Modal>
  );
}
