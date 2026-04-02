import { useSSEStore, type SSEStatus } from '../../hooks/use-sse';

/**
 * Subtle connection status indicator.
 * Only visible when SSE is reconnecting or in error state.
 */
export function ConnectionStatus() {
  const status: SSEStatus = useSSEStore((s) => s.status);

  if (status === 'connected' || status === 'disconnected') return null;

  const label = status === 'connecting' ? 'Reconnecting...' : 'Connection lost — retrying...';

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 pointer-events-none" role="status" aria-live="polite">
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface border border-border shadow-lg text-xs text-muted animate-pulse">
        <span className="inline-block w-2 h-2 rounded-full bg-amber-400" />
        {label}
      </div>
    </div>
  );
}
