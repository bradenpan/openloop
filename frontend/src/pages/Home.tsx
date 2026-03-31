import { useState } from 'react';
import { $api } from '../api/hooks';
import { AttentionItems } from '../components/home/attention-items';
import { ActiveAgents } from '../components/home/active-agents';
import { SpaceList } from '../components/home/space-list';
import { TodoOverview } from '../components/home/todo-overview';
import { ConversationList } from '../components/home/conversation-list';
import { WelcomeCard } from '../components/home/welcome-card';
import { CreateSpaceModal } from '../components/home/create-space-modal';

export default function Home() {
  const [welcomeModalOpen, setWelcomeModalOpen] = useState(false);

  const dashboard = $api.useQuery('get', '/api/v1/home/dashboard');
  const spaces = $api.useQuery('get', '/api/v1/spaces');
  const todos = $api.useQuery('get', '/api/v1/todos');
  const conversations = $api.useQuery('get', '/api/v1/conversations');
  const agents = $api.useQuery('get', '/api/v1/agents');

  const isFirstRun =
    !dashboard.isLoading &&
    !spaces.isLoading &&
    dashboard.data?.total_spaces === 0;

  return (
    <div className="space-y-6 max-w-5xl">
      {/* First-run state */}
      {isFirstRun && (
        <>
          <WelcomeCard onCreateSpace={() => setWelcomeModalOpen(true)} />
          <CreateSpaceModal
            open={welcomeModalOpen}
            onClose={() => setWelcomeModalOpen(false)}
          />
        </>
      )}

      {/* 1. Attention Items */}
      <section>
        <AttentionItems dashboard={dashboard.data} isLoading={dashboard.isLoading} />
      </section>

      {/* 2. Active Agents */}
      <section>
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-2">
          Active Agents
        </h2>
        <ActiveAgents
          conversations={conversations.data}
          agents={agents.data}
          isLoading={conversations.isLoading || agents.isLoading}
        />
      </section>

      {/* 3. Spaces */}
      <section>
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-2">
          Spaces
        </h2>
        <SpaceList spaces={spaces.data} isLoading={spaces.isLoading} />
      </section>

      {/* 4. Todos */}
      <section>
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-2">
          Todos
        </h2>
        <TodoOverview
          todos={todos.data}
          spaces={spaces.data}
          isLoading={todos.isLoading || spaces.isLoading}
        />
      </section>

      {/* 5. Recent Conversations */}
      <section>
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-2">
          Recent Conversations
        </h2>
        <ConversationList
          conversations={conversations.data}
          agents={agents.data}
          spaces={spaces.data}
          isLoading={conversations.isLoading || agents.isLoading || spaces.isLoading}
        />
      </section>
    </div>
  );
}
