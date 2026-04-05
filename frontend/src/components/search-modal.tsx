import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { components } from '../api/types';

type SearchResultItem = components['schemas']['SearchResultItem'];
type SearchResponse = components['schemas']['SearchResponse'];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TYPE_LABELS: Record<string, string> = {
  messages: 'Messages',
  summaries: 'Summaries',
  memory: 'Memory',
  documents: 'Documents',
  items: 'Items',
};

const TYPE_ICONS: Record<string, string> = {
  messages: '\u{1F4AC}',
  summaries: '\u{1F4CB}',
  memory: '\u{1F9E0}',
  documents: '\u{1F4C4}',
  items: '\u2611',
};

function highlightExcerpt(html: string): string {
  // SAFETY: The backend (search_service.py :: _safe_snippet) HTML-escapes the
  // entire FTS5 snippet output, then restores only <mark>/</mark> tags from
  // null-byte delimiters that cannot appear in user content. The result is
  // guaranteed to contain no HTML other than <mark> highlight wrappers, so
  // dangerouslySetInnerHTML is safe here.
  return html;
}

// ---------------------------------------------------------------------------
// SearchModal
// ---------------------------------------------------------------------------

export function SearchModal() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const overlayRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // Ctrl+K to open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      // Small delay so the portal has rendered
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      setQuery('');
      setResults(null);
    }
  }, [open]);

  // Debounced search
  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.GET('/api/v1/search', {
        params: { query: { q, limit: 50 } },
      });
      if (data) {
        setResults(data);
      }
    } catch {
      // Silently ignore search errors
    } finally {
      setLoading(false);
    }
  }, []);

  const onInput = (value: string) => {
    setQuery(value);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => doSearch(value), 300);
  };

  const close = () => setOpen(false);

  const handleResultClick = (item: SearchResultItem) => {
    close();
    if (item.type === 'message' || item.type === 'summary') {
      // Navigate to the conversation's space
      if (item.space_id) {
        navigate(`/space/${item.space_id}`);
      }
    } else if (item.type === 'document') {
      if (item.space_id) {
        navigate(`/space/${item.space_id}`);
      }
    } else if (item.type === 'item') {
      if (item.space_id) {
        navigate(`/space/${item.space_id}`);
      }
    }
    // Memory entries don't have a natural navigation target
  };

  // Close on Escape
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      close();
    }
  };

  if (!open) return null;

  const allSections = results
    ? Object.entries(results.results).filter(([, items]) => items.length > 0)
    : [];

  return createPortal(
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] bg-black/50 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === overlayRef.current) close();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Search"
    >
      <div
        className="bg-surface border border-border rounded-xl shadow-lg w-full max-w-2xl mx-4 max-h-[60vh] flex flex-col overflow-hidden"
        onKeyDown={onKeyDown}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <svg
            className="w-5 h-5 text-muted shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => onInput(e.target.value)}
            placeholder="Search conversations, memory, documents, items..."
            className="flex-1 bg-transparent text-foreground text-sm placeholder:text-muted outline-none"
          />
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-raised text-muted border border-border">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-auto">
          {loading && (
            <div className="flex items-center justify-center py-8">
              <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {!loading && query && results && results.total_count === 0 && (
            <div className="py-8 text-center text-sm text-muted">
              No results found for &ldquo;{query}&rdquo;
            </div>
          )}

          {!loading && !query && (
            <div className="py-8 text-center text-sm text-muted">
              Start typing to search across your workspace
            </div>
          )}

          {!loading &&
            allSections.map(([type, items]) => (
              <div key={type}>
                <div className="px-4 py-2 text-[11px] font-semibold text-muted uppercase tracking-wider bg-raised/50 border-b border-border sticky top-0">
                  {TYPE_ICONS[type] ?? ''} {TYPE_LABELS[type] ?? type} ({items.length})
                </div>
                {items.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => handleResultClick(item)}
                    className="w-full text-left px-4 py-3 hover:bg-raised transition-colors border-b border-border/50 cursor-pointer"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium text-foreground truncate">
                        {item.title}
                      </span>
                      {item.space_name && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-primary/15 text-primary shrink-0">
                          {item.space_name}
                        </span>
                      )}
                    </div>
                    {/* Safe: excerpt is HTML-escaped server-side with only <mark> allowed through.
                        See: backend/openloop/services/search_service.py :: _safe_snippet() */}
                    <div
                      className="text-xs text-muted line-clamp-2 [&_mark]:bg-primary/30 [&_mark]:text-foreground [&_mark]:rounded-sm [&_mark]:px-0.5"
                      dangerouslySetInnerHTML={{
                        __html: highlightExcerpt(item.excerpt),
                      }}
                    />
                    <div className="text-[10px] text-muted/60 mt-1">
                      {new Date(item.created_at).toLocaleDateString()}
                    </div>
                  </button>
                ))}
              </div>
            ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// SearchButton (for sidebar)
// ---------------------------------------------------------------------------

export function SearchButton({ collapsed }: { collapsed?: boolean }) {
  // The actual open/close is handled by the SearchModal's Ctrl+K listener.
  // This button simply dispatches the same key event pattern.
  const handleClick = () => {
    document.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: 'k',
        ctrlKey: true,
        bubbles: true,
      }),
    );
  };

  if (collapsed) {
    return (
      <button
        onClick={handleClick}
        className="p-2 rounded-md text-muted hover:text-foreground hover:bg-raised transition-colors cursor-pointer"
        aria-label="Search"
        title="Search (Ctrl+K)"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
          />
        </svg>
      </button>
    );
  }

  return (
    <button
      onClick={handleClick}
      className="flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm text-muted hover:bg-raised hover:text-foreground transition-colors cursor-pointer"
      title="Search (Ctrl+K)"
    >
      <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
        />
      </svg>
      <span>Search</span>
      <kbd className="ml-auto text-[10px] font-mono bg-raised text-muted border border-border px-1.5 py-0.5 rounded">
        Ctrl+K
      </kbd>
    </button>
  );
}
