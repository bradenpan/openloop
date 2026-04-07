import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button } from '../ui';

interface ConversationHeaderProps {
  conversationId: string;
  onClose?: () => void;
}

const MODEL_OPTIONS = [
  { value: 'haiku', label: 'Haiku' },
  { value: 'sonnet', label: 'Sonnet' },
  { value: 'opus', label: 'Opus' },
] as const;

export function ConversationHeader({ conversationId, onClose }: ConversationHeaderProps) {
  const queryClient = useQueryClient();

  const { data: conversation } = $api.useQuery('get', '/api/v1/conversations/{conversation_id}', {
    params: { path: { conversation_id: conversationId } },
  });

  const closeConversation = $api.useMutation('post', '/api/v1/conversations/{conversation_id}/close');

  const updateConversation = $api.useMutation(
    'patch',
    '/api/v1/conversations/{conversation_id}',
    {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/conversations'] });
      },
      onError: () => {
        queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/conversations'] });
      },
    },
  );

  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState('');

  // Fetch agents for agent selector
  const { data: agentsData } = $api.useQuery('get', '/api/v1/agents');
  const agents = agentsData ?? [];

  const displayName = conversation?.name ?? 'Conversation';
  const currentModel = conversation?.model_override ?? 'sonnet';
  const isClosed = conversation?.status === 'closed';

  const handleNameClick = () => {
    if (isClosed) return;
    setNameValue(displayName);
    setEditingName(true);
  };

  const handleNameBlur = () => {
    setEditingName(false);
    if (nameValue.trim() && nameValue.trim() !== displayName) {
      updateConversation.mutate({
        params: { path: { conversation_id: conversationId } },
        body: { name: nameValue.trim() },
      });
    }
  };

  const handleModelChange = (value: string) => {
    updateConversation.mutate({
      params: { path: { conversation_id: conversationId } },
      body: { model_override: value },
    });
  };

  const handleAgentChange = (agentId: string) => {
    updateConversation.mutate({
      params: { path: { conversation_id: conversationId } },
      body: { agent_id: agentId },
    });
  };

  const handleClose = () => {
    closeConversation.mutate(
      { params: { path: { conversation_id: conversationId } } },
      { onSuccess: () => onClose?.() },
    );
  };

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-surface shrink-0">
      {/* Conversation name — inline editable */}
      <div className="flex-1 min-w-0">
        {editingName ? (
          <input
            type="text"
            value={nameValue}
            onChange={(e) => setNameValue(e.target.value)}
            onBlur={handleNameBlur}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleNameBlur();
              if (e.key === 'Escape') setEditingName(false);
            }}
            autoFocus
            className="bg-raised text-foreground border border-border rounded px-2 py-1 text-sm font-semibold w-full focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          />
        ) : (
          <button
            type="button"
            onClick={handleNameClick}
            className="text-sm font-semibold text-foreground truncate max-w-full text-left cursor-pointer hover:text-primary transition-colors"
            title={isClosed ? displayName : 'Click to edit name'}
          >
            {displayName}
          </button>
        )}
        {isClosed && (
          <span className="text-xs text-muted ml-2">(closed)</span>
        )}
      </div>

      {/* Agent selector */}
      <select
        value={conversation?.agent_id ?? ''}
        onChange={(e) => handleAgentChange(e.target.value)}
        disabled={isClosed}
        aria-label="Agent"
        className="bg-raised text-foreground text-xs border border-border rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
      >
        {agents.map((agent) => (
          <option key={agent.id} value={agent.id}>
            {agent.name}
          </option>
        ))}
      </select>

      {/* Model selector */}
      <select
        value={currentModel}
        onChange={(e) => handleModelChange(e.target.value)}
        disabled={isClosed}
        aria-label="Model"
        className="bg-raised text-foreground text-xs border border-border rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
      >
        {MODEL_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Close button */}
      {!isClosed && (
        <Button
          size="sm"
          variant="ghost"
          onClick={handleClose}
          loading={closeConversation.isPending}
          title="Close conversation"
        >
          &#x2715;
        </Button>
      )}
    </div>
  );
}
