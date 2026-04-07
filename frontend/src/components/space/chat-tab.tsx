import { useState, useEffect, useRef, useMemo, useCallback, useReducer } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../../api/hooks';
import { Button, Badge } from '../ui';
import { ConversationPanel } from '../conversation';
import { formatDate } from '../../utils/dates';
import { getWidgetComponent } from './widget-registry';
import type { components } from '../../api/types';

type WidgetResponse = components['schemas']['WidgetResponse'];

// --- State persistence ---

interface ChatTabState {
  openTabs: string[]; // conversation IDs
  activeTab: string | null;
  sidebarCollapsed: boolean;
}

function getStorageKey(spaceId: string) {
  return `openloop:chat-tab:${spaceId}`;
}

function loadState(spaceId: string): ChatTabState {
  try {
    const raw = localStorage.getItem(getStorageKey(spaceId));
    if (raw) return JSON.parse(raw);
  } catch {
    // ignore
  }
  return { openTabs: [], activeTab: null, sidebarCollapsed: false };
}

function saveState(spaceId: string, state: ChatTabState) {
  try {
    localStorage.setItem(getStorageKey(spaceId), JSON.stringify(state));
  } catch {
    // ignore
  }
}

// --- Tab state reducer ---

interface TabState {
  openTabs: string[];
  activeTab: string | null;
}

type TabAction =
  | { type: 'open'; convId: string }
  | { type: 'close'; convId: string }
  | { type: 'select'; convId: string }
  | { type: 'cleanup'; validIds: Set<string> }
  | { type: 'reset'; state: TabState };

function tabReducer(state: TabState, action: TabAction): TabState {
  switch (action.type) {
    case 'open': {
      const tabs = state.openTabs.includes(action.convId)
        ? state.openTabs
        : [...state.openTabs, action.convId];
      return { openTabs: tabs, activeTab: action.convId };
    }
    case 'close': {
      const tabs = state.openTabs.filter((id) => id !== action.convId);
      const active = state.activeTab === action.convId
        ? (tabs.length > 0 ? tabs[tabs.length - 1] : null)
        : state.activeTab;
      return { openTabs: tabs, activeTab: active };
    }
    case 'select':
      return { ...state, activeTab: action.convId };
    case 'cleanup': {
      const tabs = state.openTabs.filter((id) => action.validIds.has(id));
      if (tabs.length === state.openTabs.length) return state; // no change
      const active = state.activeTab && action.validIds.has(state.activeTab)
        ? state.activeTab
        : (tabs[0] ?? null);
      return { openTabs: tabs, activeTab: active };
    }
    case 'reset':
      return action.state;
  }
}

// --- Chat Tab ---

const EXCLUDED_TYPES = new Set(['todo_panel', 'conversations', 'kanban_board', 'data_table', 'document_panel', 'google_sheet']);

interface ChatTabProps {
  spaceId: string;
  widgets: WidgetResponse[];
  onSelectDocument?: (documentId: string) => void;
}

export function ChatTab({ spaceId, widgets, onSelectDocument }: ChatTabProps) {
  const queryClient = useQueryClient();

  // Load persisted state (parse localStorage once)
  const [initState] = useState(() => loadState(spaceId));
  const [tabState, dispatch] = useReducer(tabReducer, {
    openTabs: initState.openTabs,
    activeTab: initState.activeTab,
  });
  const { openTabs, activeTab } = tabState;
  const [sidebarCollapsed, setSidebarCollapsed] = useState(initState.sidebarCollapsed);
  const skipPersistRef = useRef(false);

  // Reset when space changes
  useEffect(() => {
    const saved = loadState(spaceId);
    skipPersistRef.current = true;
    dispatch({ type: 'reset', state: { openTabs: saved.openTabs, activeTab: saved.activeTab } });
    setSidebarCollapsed(saved.sidebarCollapsed);
  }, [spaceId]);

  // Persist state changes
  useEffect(() => {
    if (skipPersistRef.current) {
      skipPersistRef.current = false;
      return;
    }
    saveState(spaceId, { openTabs, activeTab, sidebarCollapsed });
  }, [spaceId, openTabs, activeTab, sidebarCollapsed]);

  // Conversations for this space
  const { data: convsData, isLoading } = $api.useQuery('get', '/api/v1/conversations', {
    params: { query: { space_id: spaceId } },
  });
  const conversations = convsData ?? [];

  // Agents for creating new conversations
  const { data: agentsData } = $api.useQuery('get', '/api/v1/agents');
  const odinAgent = agentsData?.find((a) => a.name?.toLowerCase() === 'odin');

  const createConversation = $api.useMutation('post', '/api/v1/conversations', {
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['get', '/api/v1/conversations'] });
      openConversation(data.id);
    },
  });

  // Filter out widgets that are sidebars or core views — only show extra widgets
  const rightWidgets = useMemo(
    () => widgets.filter((w) => !EXCLUDED_TYPES.has(w.widget_type)),
    [widgets],
  );

  // --- Tab management ---

  const openConversation = useCallback((convId: string) => {
    dispatch({ type: 'open', convId });
  }, []);

  const closeTab = useCallback((convId: string) => {
    dispatch({ type: 'close', convId });
  }, []);

  function handleNewConversation() {
    if (!odinAgent) return;
    createConversation.mutate({
      body: {
        agent_id: odinAgent.id,
        name: `Chat ${new Date().toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}`,
        space_id: spaceId,
        model_override: 'sonnet',
      },
    });
  }

  // Clean up tabs that reference deleted conversations
  useEffect(() => {
    if (!convsData) return;
    const validIds = new Set(convsData.map((c) => c.id));
    dispatch({ type: 'cleanup', validIds });
  }, [convsData]);

  // Get conversation names for tabs
  const convMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of conversations) {
      map.set(c.id, c.name);
    }
    return map;
  }, [conversations]);

  return (
    <div className="flex h-full">
      {/* Left sidebar — conversation list */}
      {sidebarCollapsed ? (
        <div className="flex flex-col items-center py-3 w-10 shrink-0 bg-surface border-r border-border">
          <button
            onClick={() => setSidebarCollapsed(false)}
            className="text-muted hover:text-foreground transition-colors p-1.5 rounded-md hover:bg-raised cursor-pointer"
            aria-label="Expand chat list"
            title="Conversations"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 3h12v8H6l-4 3V3z" />
            </svg>
          </button>
          <span className="text-[10px] text-muted mt-1 [writing-mode:vertical-rl] rotate-180">Chats</span>
        </div>
      ) : (
        <div className="flex flex-col w-56 shrink-0 bg-surface border-r border-border">
          {/* Header */}
          <div className="px-3 py-2.5 border-b border-border flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">Conversations</h3>
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={handleNewConversation}
                disabled={!odinAgent || createConversation.isPending}
              >
                + New
              </Button>
              <button
                onClick={() => setSidebarCollapsed(true)}
                className="text-muted hover:text-foreground transition-colors p-1 rounded-md hover:bg-raised cursor-pointer"
                aria-label="Collapse chat list"
              >
                &#x2190;
              </button>
            </div>
          </div>

          {/* Conversation list */}
          <div className="flex-1 overflow-auto">
            {isLoading && <p className="px-3 py-4 text-sm text-muted">Loading...</p>}

            {!isLoading && conversations.length === 0 && (
              <div className="px-3 py-6 text-center">
                <p className="text-sm text-muted">No conversations yet.</p>
                <p className="text-xs text-muted mt-1">Click + New to start.</p>
              </div>
            )}

            {conversations.map((conv) => (
              <button
                key={conv.id}
                onClick={() => openConversation(conv.id)}
                className={`w-full text-left px-3 py-2.5 transition-colors border-b border-border/50 cursor-pointer ${
                  activeTab === conv.id
                    ? 'bg-primary/10 border-l-2 border-l-primary'
                    : 'hover:bg-raised/50'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-foreground truncate">{conv.name}</span>
                  <Badge
                    variant={conv.status === 'active' ? 'success' : 'info'}
                  >
                    {conv.status}
                  </Badge>
                </div>
                <div className="text-[11px] text-muted">
                  {formatDate(conv.created_at)}
                  {conv.model_override && <span className="ml-1">· {conv.model_override}</span>}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Center — conversation tabs + active conversation */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Tab bar */}
        {openTabs.length > 0 && (
          <ConversationTabBar
            tabs={openTabs}
            activeTab={activeTab}
            convMap={convMap}
            onSelect={(id) => dispatch({ type: 'select', convId: id })}
            onClose={closeTab}
            onNew={handleNewConversation}
            canCreate={!!odinAgent && !createConversation.isPending}
          />
        )}

        {/* Active conversation or empty state */}
        {activeTab ? (
          <div className="flex-1 min-h-0" role="tabpanel">
            <ConversationPanel
              key={activeTab}
              conversationId={activeTab}
            />
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <p className="text-muted text-sm mb-3">
                {conversations.length === 0
                  ? 'No conversations yet in this space.'
                  : 'Select a conversation or start a new one.'}
              </p>
              <Button
                size="sm"
                onClick={handleNewConversation}
                disabled={!odinAgent || createConversation.isPending}
              >
                {createConversation.isPending ? 'Creating...' : '+ New Conversation'}
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Right widget column (optional) */}
      {rightWidgets.length > 0 && (
        <div className="flex flex-col w-72 shrink-0 border-l border-border overflow-auto">
          {rightWidgets.map((widget) => {
            const Comp = getWidgetComponent(widget.widget_type);
            return (
              <div key={widget.id} className="min-h-[200px]">
                <Comp
                  spaceId={spaceId}
                  widgetId={widget.id}
                  config={widget.config}
                  size={widget.size}
                  onSelectDocument={onSelectDocument}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// --- Conversation Tab Bar ---

interface ConversationTabBarProps {
  tabs: string[];
  activeTab: string | null;
  convMap: Map<string, string>;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onNew: () => void;
  canCreate: boolean;
}

function ConversationTabBar({ tabs, activeTab, convMap, onSelect, onClose, onNew, canCreate }: ConversationTabBarProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  return (
    <div className="flex items-center border-b border-border bg-surface/50 shrink-0">
      {/* Scrollable tab area */}
      <div
        ref={scrollRef}
        role="tablist"
        className="flex-1 flex items-center overflow-x-auto min-w-0"
        style={{ scrollbarWidth: 'thin' }}
      >
        {tabs.map((id) => {
          const name = convMap.get(id) ?? 'Conversation';
          const isActive = id === activeTab;
          return (
            <div
              key={id}
              role="tab"
              tabIndex={0}
              aria-selected={isActive}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-r border-border/50 cursor-pointer shrink-0 max-w-[180px] transition-colors ${
                isActive
                  ? 'bg-background text-foreground border-b-2 border-b-primary -mb-px'
                  : 'text-muted hover:text-foreground hover:bg-raised/50'
              }`}
              onClick={() => onSelect(id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelect(id);
                }
              }}
            >
              <span className="truncate">{name}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(id);
                }}
                className="text-muted hover:text-destructive p-0.5 rounded hover:bg-destructive/10 transition-colors shrink-0"
                aria-label="Close tab"
              >
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <path d="M2.5 2.5l5 5M7.5 2.5l-5 5" />
                </svg>
              </button>
            </div>
          );
        })}
      </div>

      {/* New tab button */}
      <button
        onClick={onNew}
        disabled={!canCreate}
        className="px-2.5 py-2 text-muted hover:text-foreground hover:bg-raised transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shrink-0 border-l border-border/50"
        aria-label="New conversation"
        title="New conversation"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M7 3v8M3 7h8" />
        </svg>
      </button>
    </div>
  );
}
