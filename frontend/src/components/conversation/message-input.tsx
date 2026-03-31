import { useRef, useState, type KeyboardEvent } from 'react';
import { Button } from '../ui';

interface MessageInputProps {
  conversationId: string;
  disabled: boolean;
  onSend: (content: string) => void;
}

export function MessageInput({ disabled, onSend }: MessageInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue('');
    // Reset textarea height after clearing
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    // Auto-resize: reset to auto then set to scrollHeight, capped at 200px
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  return (
    <div className="flex items-end gap-2 px-4 py-3 border-t border-border bg-surface">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          handleInput();
        }}
        onKeyDown={handleKeyDown}
        placeholder={disabled ? 'Waiting for response...' : 'Send a message...'}
        disabled={disabled}
        rows={1}
        className="flex-1 resize-none bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-150"
      />
      <Button
        size="md"
        variant="primary"
        onClick={handleSend}
        disabled={disabled || !value.trim()}
      >
        Send
      </Button>
    </div>
  );
}
