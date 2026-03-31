import { useState } from 'react';
import { $api } from '../api/hooks';
import type { components } from '../api/types';
import { Button } from '../components/ui';
import { AgentList } from '../components/agents/agent-list';
import { AgentFormModal } from '../components/agents/agent-form-modal';
import { DeleteAgentModal } from '../components/agents/delete-agent-modal';
import { PermissionMatrix } from '../components/agents/permission-matrix';

type Agent = components['schemas']['AgentResponse'];

export default function Agents() {
  const [formOpen, setFormOpen] = useState(false);
  const [editAgent, setEditAgent] = useState<Agent | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Agent | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  const { data, isLoading } = $api.useQuery('get', '/api/v1/agents');
  const agents: Agent[] = data ?? [];

  // Keep selectedAgent reference in sync with fresh data
  const currentSelected = selectedAgent
    ? agents.find((a) => a.id === selectedAgent.id) ?? null
    : null;

  const handleEdit = (agent: Agent) => {
    setEditAgent(agent);
    setFormOpen(true);
  };

  const handleDelete = (agent: Agent) => {
    setDeleteTarget(agent);
  };

  const handleSelect = (agent: Agent) => {
    setSelectedAgent((prev) => (prev?.id === agent.id ? null : agent));
  };

  const handleCloseForm = () => {
    setFormOpen(false);
    setEditAgent(null);
  };

  const handleDeleted = () => {
    if (selectedAgent?.id === deleteTarget?.id) {
      setSelectedAgent(null);
    }
  };

  return (
    <div className="max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-foreground">Agents</h1>
        <Button onClick={() => { setEditAgent(null); setFormOpen(true); }}>
          New Agent
        </Button>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted">Loading agents...</p>
      ) : (
        <AgentList
          agents={agents}
          selectedId={currentSelected?.id ?? null}
          onSelect={handleSelect}
          onEdit={handleEdit}
          onDelete={handleDelete}
        />
      )}

      {currentSelected && (
        <div className="mt-6">
          <PermissionMatrix agent={currentSelected} />
        </div>
      )}

      <AgentFormModal
        open={formOpen}
        onClose={handleCloseForm}
        agent={editAgent}
      />

      <DeleteAgentModal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        agent={deleteTarget}
        onDeleted={handleDeleted}
      />
    </div>
  );
}
