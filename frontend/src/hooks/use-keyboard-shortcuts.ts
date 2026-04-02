import { useEffect } from 'react';

function isInputFocused(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    (el as HTMLElement).isContentEditable
  );
}

interface ShortcutHandlers {
  onFocusOdin?: () => void;
  onClosePanel?: () => void;
  onNewItem?: () => void;
  onToggleHelp?: () => void;
}

export function useKeyboardShortcuts({
  onFocusOdin,
  onClosePanel,
  onNewItem,
  onToggleHelp,
}: ShortcutHandlers) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      // Don't intercept when modifier keys are held (except for Escape)
      const hasModifier = e.ctrlKey || e.metaKey || e.altKey;

      if (e.key === 'Escape') {
        onClosePanel?.();
        return;
      }

      // Skip all other shortcuts when focused in an input
      if (isInputFocused() || hasModifier) return;

      switch (e.key) {
        case '/':
          e.preventDefault();
          onFocusOdin?.();
          break;
        case 'n':
          e.preventDefault();
          onNewItem?.();
          break;
        case '?':
          e.preventDefault();
          onToggleHelp?.();
          break;
      }
    }

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onFocusOdin, onClosePanel, onNewItem, onToggleHelp]);
}
