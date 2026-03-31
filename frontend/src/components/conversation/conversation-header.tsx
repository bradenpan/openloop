import { useState } from 'react';
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
  const { data: conversation } = $api.useQuery('get', '/api/v1/conversations/{conversation_id}', {
    params: { path: { conversation_id: conversationId } },
  });

  const closeConversation = $api.useMutation('post', '/api/v1/conversations/{conversation_id}/close');

  // Local state for name editing — no PATCH endpoint exists yet
  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState('');

  // Local model override — no PATCH endpoint exists yet
  const [localModel, setLocalModel] = useState<string | null>(null);

  const displayName = conversation?.name ?? 'Conversation';
  const currentModel = localModel ?? conversation?.model_override ?? 'sonnet';
  const isClosed = conversation?.status === 'closed';

  const handleNameClick = () => {
    if (isClosed) return;
    setNameValue(displayName);
    setEditingName(true);
  };

  const handleNameBlur = () => {
    setEditingName(false);
    if (nameValue.trim() && nameValue.trim() !== displayName) {
      // TODO: Needs PATCH /api/v1/conversations/{conversation_id} endpoint to persist name changes
      console.warn('Conversation name editing requires a PATCH endpoint that does not exist yet.');
    }
  };

  const handleModelChange = (value: string) => {
    setLocalModel(value);
    // TODO: Needs PATCH /api/v1/conversations/{conversation_id} endpoint to persist model override
    console.warn('Model override requires a PATCH endpoint that does not exist yet.');
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

      {/* Model selector */}
      <select
        value={currentModel}
        onChange={(e) => handleModelChange(e.target.value)}
        disabled={isClosed}
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
