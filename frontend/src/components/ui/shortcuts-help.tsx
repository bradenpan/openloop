import { useEffect } from 'react';
import { createPortal } from 'react-dom';

interface ShortcutsHelpProps {
  open: boolean;
  onClose: () => void;
}

const shortcuts = [
  { keys: '/', description: 'Focus Odin input' },
  { keys: 'Ctrl+K', description: 'Open search' },
  { keys: 'n', description: 'New item (when in a space)' },
  { keys: 'Esc', description: 'Close panel / modal' },
  { keys: '?', description: 'Toggle this help overlay' },
];

export function ShortcutsHelp({ open, onClose }: ShortcutsHelpProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="bg-surface border border-border rounded-xl shadow-lg w-full max-w-sm mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-border flex items-center justify-between">
          <h2 className="text-base font-semibold text-foreground">Keyboard Shortcuts</h2>
          <button
            onClick={onClose}
            className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised"
            aria-label="Close"
          >
            &#x2715;
          </button>
        </div>
        <div className="p-5">
          <div className="flex flex-col gap-3">
            {shortcuts.map((s) => (
              <div key={s.keys} className="flex items-center justify-between">
                <span className="text-sm text-foreground">{s.description}</span>
                <kbd className="px-2 py-0.5 rounded bg-raised border border-border text-xs font-mono text-muted">
                  {s.keys}
                </kbd>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
