import { useState, useCallback } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './sidebar';
import { OdinBar } from './odin-bar';
import { ConnectionStatus } from './connection-status';
import { SearchModal } from '../search-modal';
import { ToastContainer, ShortcutsHelp } from '../ui';
import { FadeIn } from '../ui/fade-in';
import { useSSEConnection } from '../../hooks/use-sse';
import { useKeyboardShortcuts } from '../../hooks/use-keyboard-shortcuts';
import { useDocumentTitle } from '../../hooks/use-document-title';
import { useUIStore } from '../../stores/ui-store';

export function AppShell() {
  useSSEConnection();
  useDocumentTitle();

  const location = useLocation();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const toggleOdin = useUIStore((s) => s.toggleOdin);
  const odinExpanded = useUIStore((s) => s.odinExpanded);

  const handleFocusOdin = useCallback(() => {
    if (!odinExpanded) toggleOdin();
    // Focus the Odin input after it expands
    requestAnimationFrame(() => {
      const input = document.querySelector<HTMLInputElement>('[data-odin-input]');
      input?.focus();
    });
  }, [odinExpanded, toggleOdin]);

  const handleClosePanel = useCallback(() => {
    if (shortcutsOpen) {
      setShortcutsOpen(false);
    }
    // Panels and modals handle their own Escape via their own keydown listeners
  }, [shortcutsOpen]);

  const handleToggleHelp = useCallback(() => {
    setShortcutsOpen((prev) => !prev);
  }, []);

  useKeyboardShortcuts({
    onFocusOdin: handleFocusOdin,
    onClosePanel: handleClosePanel,
    onToggleHelp: handleToggleHelp,
  });

  return (
    <div className="flex h-screen bg-background text-foreground font-sans">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0">
        <main className="flex-1 overflow-auto p-6">
          <FadeIn key={location.pathname}>
            <Outlet />
          </FadeIn>
        </main>
        <OdinBar />
      </div>
      <SearchModal />
      <ConnectionStatus />
      <ToastContainer />
      <ShortcutsHelp open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}
