import { useNavigate } from 'react-router-dom';
import type { components } from '../../api/types';
import { Card, CardBody, Badge } from '../ui';

type Conversation = components['schemas']['ConversationResponse'];
type Agent = components['schemas']['AgentResponse'];
type Space = components['schemas']['SpaceResponse'];

interface ConversationListProps {
  conversations: Conversation[] | undefined;
  agents: Agent[] | undefined;
  spaces: Space[] | undefined;
  isLoading: boolean;
}

const statusVariant: Record<string, 'default' | 'success' | 'warning' | 'danger' | 'info'> = {
  active: 'success',
  closed: 'info',
  error: 'danger',
};

function timeAgo(dateStr: string): string {
  const ms = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function Skeleton() {
  return (
    <div className="space-y-1.5">
      {[1, 2, 3].map((i) => (
        <Card key={i}>
          <CardBody className="flex items-center gap-3 py-2.5 px-3">
            <div className="h-4 w-36 rounded bg-raised animate-pulse" />
            <div className="ml-auto h-4 w-16 rounded-full bg-raised animate-pulse" />
          </CardBody>
        </Card>
      ))}
    </div>
  );
}

export function ConversationList({ conversations, agents, spaces, isLoading }: ConversationListProps) {
  const navigate = useNavigate();

  if (isLoading) return <Skeleton />;

  if (!conversations || conversations.length === 0) {
    return <p className="text-sm text-muted py-2">No conversations yet.</p>;
  }

  const agentMap = new Map(agents?.map((a) => [a.id, a.name]) ?? []);
  const spaceMap = new Map(spaces?.map((s) => [s.id, s.name]) ?? []);

  // Most recent first
  const sorted = [...conversations].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );

  return (
    <div className="space-y-1.5">
      {sorted.slice(0, 15).map((conv) => (
        <Card
          key={conv.id}
          className={`cursor-pointer hover:border-primary/50 transition-colors duration-150 ${
            !conv.space_id ? 'opacity-70' : ''
          }`}
        >
          <CardBody
            className="flex items-center gap-3 py-2 px-3"
            onClick={() => {
              if (conv.space_id) navigate(`/space/${conv.space_id}`);
            }}
          >
            <div className="flex flex-col min-w-0 flex-1">
              <span className="text-sm font-medium text-foreground truncate">{conv.name}</span>
              <span className="text-xs text-muted truncate">
                {agentMap.get(conv.agent_id) ?? 'Unknown agent'}
                {conv.space_id && spaceMap.get(conv.space_id)
                  ? ` \u00b7 ${spaceMap.get(conv.space_id)}`
                  : ''}
              </span>
            </div>
            <span className="text-xs text-muted shrink-0">{timeAgo(conv.updated_at)}</span>
            <Badge variant={statusVariant[conv.status] ?? 'info'} className="shrink-0">
              {conv.status}
            </Badge>
          </CardBody>
        </Card>
      ))}
    </div>
  );
}
