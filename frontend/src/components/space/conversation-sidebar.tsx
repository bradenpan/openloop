import { useState } from 'react';
import { $api } from '../../api/hooks';
import { Badge, Button, Panel } from '../ui';
import { formatDate } from '../../utils/dates';
import { NewConversationModal } from './new-conversation-modal';
import { ConversationPanel } from '../conversation';

interface ConversationSidebarProps {
  spaceId: string;
  collapsed: boolean;
  onToggle: () => void;
}

export function ConversationSidebar({ spaceId, collapsed, onToggle }: ConversationSidebarProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);

  const { data: convsData, isLoading } = $api.useQuery('get', '/api/v1/conversations', {
    params: { query: { space_id: spaceId } },
  });
  const conversations = convsData ?? [];

  function handleClick(conversationId: string) {
    setActiveConversationId((prev) => prev === conversationId ? null : conversationId);
  }

  if (collapsed) {
    return (
      <div className="flex flex-col items-center py-3 w-10 shrink-0 bg-surface border-l border-border">
        <button
          onClick={onToggle}
          className="text-muted hover:text-foreground transition-colors p-1.5 rounded-md hover:bg-raised cursor-pointer"
          aria-label="Expand conversations panel"
          title="Conversations"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 3h12v8H6l-4 3V3z" />
          </svg>
        </button>
        <span className="text-[10px] text-muted mt-1 [writing-mode:vertical-rl] rotate-180">Chat</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col w-64 min-w-[224px] shrink-0 bg-surface border-l border-border">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-border flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">Conversations</h3>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" onClick={() => setModalOpen(true)}>
            + New
          </Button>
          <button
            onClick={onToggle}
            className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised cursor-pointer"
            aria-label="Collapse conversations panel"
          >
            &#x2192;
          </button>
        </div>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-auto">
        {isLoading && <p className="px-3 py-4 text-sm text-muted">Loading...</p>}

        {!isLoading && conversations.length === 0 && (
          <div className="px-3 py-6 text-center">
            <p className="text-sm text-muted">No conversations yet.</p>
            <p className="text-xs text-muted mt-1">Start a conversation to work with an agent.</p>
          </div>
        )}

        {conversations.map((conv) => (
          <button
            key={conv.id}
            onClick={() => handleClick(conv.id)}
            className="w-full text-left px-3 py-2.5 hover:bg-raised/50 transition-colors border-b border-border/50 cursor-pointer"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium text-foreground truncate">{conv.name}</span>
              <Badge
                variant={conv.status === 'active' ? 'success' : 'info'}
                className="ml-2 shrink-0"
              >
                {conv.status}
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-muted">
              <span>{formatDate(conv.created_at)}</span>
              {conv.model_override && <span>({conv.model_override})</span>}
            </div>
          </button>
        ))}
      </div>

      <NewConversationModal open={modalOpen} onClose={() => setModalOpen(false)} spaceId={spaceId} />

      {/* Active conversation panel rendered alongside the sidebar */}
      <Panel
        open={!!activeConversationId}
        onClose={() => setActiveConversationId(null)}
        width="600px"
        noPadding
      >
        {activeConversationId && (
          <ConversationPanel
            conversationId={activeConversationId}
            onClose={() => setActiveConversationId(null)}
          />
        )}
      </Panel>
    </div>
  );
}
