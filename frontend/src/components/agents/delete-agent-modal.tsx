import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import type { components } from '../../api/types';
import { Modal } from '../ui';
import { Button } from '../ui';

type Agent = components['schemas']['AgentResponse'];

interface DeleteAgentModalProps {
  open: boolean;
  onClose: () => void;
  agent: Agent | null;
  onDeleted: () => void;
}

export function DeleteAgentModal({ open, onClose, agent, onDeleted }: DeleteAgentModalProps) {
  const queryClient = useQueryClient();

  const deleteAgent = $api.useMutation('delete', '/api/v1/agents/{agent_id}', {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/agents'] });
      onDeleted();
      onClose();
    },
  });

  const handleDelete = () => {
    if (!agent) return;
    deleteAgent.mutate({
      params: { path: { agent_id: agent.id } },
    });
  };

  return (
    <Modal open={open} onClose={onClose} title="Delete Agent">
      <div className="flex flex-col gap-4">
        <p className="text-sm text-foreground">
          Are you sure you want to delete <span className="font-semibold">{agent?.name}</span>?
          This action cannot be undone.
        </p>

        {deleteAgent.error && (
          <p className="text-sm text-destructive">
            {deleteAgent.error instanceof Error ? deleteAgent.error.message : 'Failed to delete agent'}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose} disabled={deleteAgent.isPending}>
            Cancel
          </Button>
          <Button variant="danger" onClick={handleDelete} loading={deleteAgent.isPending}>
            Delete
          </Button>
        </div>
      </div>
    </Modal>
  );
}
