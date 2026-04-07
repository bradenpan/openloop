import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button, Input } from '../ui';
import type { WidgetProps } from './widget-registry';

/**
 * Convert a Google Sheets URL into an embed-friendly form.
 * Strips existing query/hash and appends `?rm=minimal` for a cleaner in-app
 * experience (removes most of Google's chrome while keeping edit capability).
 */
function toEmbedUrl(raw: string): string | null {
  try {
    const url = new URL(raw);
    // Only allow Google Sheets URLs
    if (url.hostname !== 'docs.google.com') return null;
    // Keep everything up to and including /edit (or the full path if no /edit)
    const editIdx = url.pathname.indexOf('/edit');
    const pathname = editIdx !== -1
      ? url.pathname.slice(0, editIdx + '/edit'.length)
      : url.pathname;
    return `${url.origin}${pathname}?rm=minimal`;
  } catch {
    return null;
  }
}

// --- Setup form (no sheet URL configured) ---

function SetupView({
  spaceId,
  widgetId,
}: {
  spaceId: string;
  widgetId: string;
}) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState('');

  const updateWidget = $api.useMutation(
    'patch',
    '/api/v1/spaces/{space_id}/layout/widgets/{widget_id}',
    {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: ['get', '/api/v1/spaces/{space_id}/layout'],
        });
      },
    },
  );

  function handleConnect() {
    const trimmed = url.trim();
    if (!trimmed) return;
    updateWidget.mutate({
      params: { path: { space_id: spaceId, widget_id: widgetId } },
      body: { config: { sheet_url: trimmed } },
    });
  }

  return (
    <div className="flex flex-col items-center justify-center h-full bg-surface border border-border rounded-lg p-8 gap-4">
      <div className="w-12 h-12 rounded-lg bg-raised flex items-center justify-center text-2xl">
        📊
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-foreground">
          No Google Sheet configured
        </p>
        <p className="text-xs text-muted mt-1">
          Paste a Google Sheets URL (docs.google.com) to embed it here.
        </p>
      </div>
      <div className="flex gap-2 w-full max-w-md">
        <div className="flex-1">
          <Input
            placeholder="https://docs.google.com/spreadsheets/d/..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleConnect();
            }}
          />
        </div>
        <Button
          variant="primary"
          size="md"
          onClick={handleConnect}
          loading={updateWidget.isPending}
          disabled={!url.trim()}
        >
          Connect
        </Button>
      </div>
    </div>
  );
}

// --- Toolbar above the iframe ---

function SheetToolbar({
  sheetUrl,
  onChangeUrl,
}: {
  sheetUrl: string;
  onChangeUrl: () => void;
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-raised/50 border-b border-border shrink-0">
      <span className="text-sm" aria-hidden="true">📊</span>
      <span className="text-sm font-medium text-foreground flex-1 min-w-0 truncate">
        Google Sheet
      </span>

      {/* Open in new tab */}
      <a
        href={sheetUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="p-1 rounded text-muted hover:text-foreground hover:bg-surface transition-colors cursor-pointer"
        title="Open in new tab"
        aria-label="Open in new tab"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M10 1.5h2.5V4" />
          <path d="M6 8l6.5-6.5" />
          <path d="M11 7.5v4a1.5 1.5 0 01-1.5 1.5h-7A1.5 1.5 0 011 11.5v-7A1.5 1.5 0 012.5 3H7" />
        </svg>
      </a>

      {/* Change / disconnect */}
      <button
        onClick={onChangeUrl}
        className="p-1 rounded text-muted hover:text-foreground hover:bg-surface transition-colors cursor-pointer"
        title="Change Sheet URL"
        aria-label="Change Sheet URL"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="7" cy="7" r="2.5" />
          <path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.76 2.76l1.06 1.06M10.18 10.18l1.06 1.06M11.24 2.76l-1.06 1.06M3.82 10.18l-1.06 1.06" />
        </svg>
      </button>
    </div>
  );
}

// --- URL editor overlay (shown when user clicks the gear) ---

function UrlEditor({
  currentUrl,
  spaceId,
  widgetId,
  onClose,
}: {
  currentUrl: string;
  spaceId: string;
  widgetId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState(currentUrl);

  const updateWidget = $api.useMutation(
    'patch',
    '/api/v1/spaces/{space_id}/layout/widgets/{widget_id}',
    {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: ['get', '/api/v1/spaces/{space_id}/layout'],
        });
        onClose();
      },
    },
  );

  function handleSave() {
    const trimmed = url.trim();
    if (!trimmed) return;
    updateWidget.mutate({
      params: { path: { space_id: spaceId, widget_id: widgetId } },
      body: { config: { sheet_url: trimmed } },
    });
  }

  function handleDisconnect() {
    updateWidget.mutate({
      params: { path: { space_id: spaceId, widget_id: widgetId } },
      body: { config: {} },
    });
  }

  return (
    <div className="absolute inset-x-0 top-0 z-10 bg-surface border-b border-border p-3 shadow-lg">
      <div className="flex gap-2 items-end">
        <div className="flex-1">
          <Input
            label="Google Sheet URL"
            placeholder="https://docs.google.com/spreadsheets/d/..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave();
              if (e.key === 'Escape') onClose();
            }}
          />
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={handleSave}
          loading={updateWidget.isPending}
          disabled={!url.trim()}
        >
          Save
        </Button>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Cancel
        </Button>
      </div>
      <div className="mt-2">
        <button
          onClick={handleDisconnect}
          className="text-xs text-destructive hover:underline cursor-pointer"
        >
          Disconnect sheet
        </button>
      </div>
    </div>
  );
}

// --- Main widget ---

export function GoogleSheetWidget({ spaceId, widgetId, config }: WidgetProps) {
  const [editing, setEditing] = useState(false);
  const sheetUrl = (config?.sheet_url as string) ?? '';

  if (!sheetUrl) {
    return <SetupView spaceId={spaceId} widgetId={widgetId} />;
  }

  const embedUrl = toEmbedUrl(sheetUrl);

  return (
    <div className="flex flex-col h-full relative">
      <SheetToolbar
        sheetUrl={sheetUrl}
        onChangeUrl={() => setEditing((v) => !v)}
      />

      {editing && (
        <UrlEditor
          currentUrl={sheetUrl}
          spaceId={spaceId}
          widgetId={widgetId}
          onClose={() => setEditing(false)}
        />
      )}

      {embedUrl ? (
        <iframe
          src={embedUrl}
          className="w-full flex-1 border-0"
          allow="clipboard-read; clipboard-write"
          sandbox="allow-scripts allow-same-origin allow-popups allow-forms allow-popups-to-escape-sandbox"
          title="Google Sheet"
        />
      ) : (
        <div className="flex-1 flex items-center justify-center bg-surface">
          <p className="text-sm text-destructive">
            Invalid URL. Only Google Sheets URLs (docs.google.com) are supported.
          </p>
        </div>
      )}
    </div>
  );
}
