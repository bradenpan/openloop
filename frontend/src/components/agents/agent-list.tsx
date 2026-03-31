import type { components } from '../../api/types';
import { Card, CardBody } from '../ui';
import { Badge } from '../ui';
import { Button } from '../ui';

type Agent = components['schemas']['AgentResponse'];

const modelBadgeVariant = (model: string) => {
  switch (model) {
    case 'opus': return 'danger' as const;
    case 'sonnet': return 'default' as const;
    case 'haiku': return 'info' as const;
    default: return 'info' as const;
  }
};

const statusBadgeVariant = (status: string) => {
  switch (status) {
    case 'active': return 'success' as const;
    case 'inactive': return 'warning' as const;
    default: return 'info' as const;
  }
};

interface AgentListProps {
  agents: Agent[];
  selectedId: string | null;
  onSelect: (agent: Agent) => void;
  onEdit: (agent: Agent) => void;
  onDelete: (agent: Agent) => void;
}

export function AgentList({ agents, selectedId, onSelect, onEdit, onDelete }: AgentListProps) {
  if (agents.length === 0) {
    return (
      <div className="text-center py-12 text-muted">
        <p className="text-sm">No agents configured yet.</p>
        <p className="text-xs mt-1">Create one to get started.</p>
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      {agents.map((agent) => (
        <Card
          key={agent.id}
          className={`cursor-pointer transition-colors hover:border-primary/50 ${
            selectedId === agent.id ? 'border-primary bg-primary/5' : ''
          }`}
        >
          <CardBody>
            <div
              className="flex items-start justify-between gap-4"
              onClick={() => onSelect(agent)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelect(agent); }}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-semibold text-foreground truncate">{agent.name}</span>
                  <Badge variant={modelBadgeVariant(agent.default_model)}>
                    {agent.default_model}
                  </Badge>
                  <Badge variant={statusBadgeVariant(agent.status)}>
                    {agent.status}
                  </Badge>
                </div>
                {agent.description && (
                  <p className="text-sm text-muted truncate">{agent.description}</p>
                )}
              </div>
              <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onEdit(agent)}
                  aria-label={`Edit ${agent.name}`}
                >
                  Edit
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => onDelete(agent)}
                  aria-label={`Delete ${agent.name}`}
                >
                  Delete
                </Button>
              </div>
            </div>
          </CardBody>
        </Card>
      ))}
    </div>
  );
}
