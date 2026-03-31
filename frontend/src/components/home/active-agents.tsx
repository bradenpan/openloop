import type { components } from '../../api/types';
import { Card, CardBody, Badge } from '../ui';

type Conversation = components['schemas']['ConversationResponse'];
type Agent = components['schemas']['AgentResponse'];

interface ActiveAgentsProps {
  conversations: Conversation[] | undefined;
  agents: Agent[] | undefined;
  isLoading: boolean;
}

function elapsedLabel(createdAt: string): string {
  const ms = Date.now() - new Date(createdAt).getTime();
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  return `${Math.floor(hrs / 24)}d`;
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[1, 2].map((i) => (
        <Card key={i}>
          <CardBody className="flex items-center gap-3 py-2.5">
            <div className="h-2 w-2 rounded-full bg-raised animate-pulse" />
            <div className="h-4 w-32 rounded bg-raised animate-pulse" />
            <div className="ml-auto h-4 w-12 rounded bg-raised animate-pulse" />
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

export function ActiveAgents({ conversations, agents, isLoading }: ActiveAgentsProps) {
  if (isLoading) return <Skeleton />;

  const active = conversations?.filter((c) => c.status === 'active') ?? [];
  const agentMap = new Map(agents?.map((a) => [a.id, a.name]) ?? []);

  if (active.length === 0) {
    return (
      <p className="text-sm text-muted py-2">No active agent sessions.</p>
    );
  }

  return (
    <div className="space-y-1.5">
      {active.map((conv) => (
        <Card key={conv.id}>
          <CardBody className="flex items-center gap-3 py-2.5 px-3">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-success" />
            </span>
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-medium text-foreground truncate">{conv.name}</span>
              <span className="text-xs text-muted truncate">
                {agentMap.get(conv.agent_id) ?? 'Unknown agent'}
              </span>
            </div>
            <Badge variant="info" className="ml-auto shrink-0">{elapsedLabel(conv.created_at)}</Badge>
          </CardBody>
        </Card>
      ))}
    </div>
  );
}
