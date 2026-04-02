/**
 * API mocking helpers for Playwright E2E tests.
 *
 * These intercept all /api/* requests so tests run without a backend.
 * Each helper returns mock data matching the actual API response shapes.
 */
import { type Page } from '@playwright/test';

// ─── Mock data factories ─────────────────────────────────────────────────────

let _idCounter = 0;
function nextId(): string {
  _idCounter++;
  return `00000000-0000-0000-0000-${String(_idCounter).padStart(12, '0')}`;
}

export function resetIdCounter() {
  _idCounter = 0;
}

export function makeSpace(overrides: Record<string, unknown> = {}) {
  const id = nextId();
  return {
    id,
    name: `Test Space ${id.slice(-3)}`,
    template: 'project',
    description: null,
    board_enabled: true,
    board_columns: ['idea', 'scoping', 'todo', 'in_progress', 'done'],
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
    ...overrides,
  };
}

export function makeAgent(overrides: Record<string, unknown> = {}) {
  const id = nextId();
  return {
    id,
    name: `Test Agent ${id.slice(-3)}`,
    description: 'A test agent',
    system_prompt: 'You are a helpful assistant.',
    default_model: 'sonnet',
    status: 'active',
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
    ...overrides,
  };
}

export function makeItem(overrides: Record<string, unknown> = {}) {
  const id = nextId();
  return {
    id,
    space_id: 'space-1',
    title: `Item ${id.slice(-3)}`,
    description: null,
    item_type: 'task',
    stage: 'todo',
    is_done: false,
    archived: false,
    priority: null,
    due_date: null,
    sort_position: 0,
    is_agent_task: false,
    parent_id: null,
    custom_fields: null,
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
    ...overrides,
  };
}

export function makeConversation(overrides: Record<string, unknown> = {}) {
  const id = nextId();
  return {
    id,
    name: `Conversation ${id.slice(-3)}`,
    agent_id: 'agent-1',
    space_id: 'space-1',
    status: 'active',
    model_override: null,
    session_id: null,
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
    ...overrides,
  };
}

export function makeAutomation(overrides: Record<string, unknown> = {}) {
  const id = nextId();
  return {
    id,
    name: `Automation ${id.slice(-3)}`,
    description: 'A test automation',
    agent_id: 'agent-1',
    instruction: 'Run daily report',
    trigger_type: 'cron',
    cron_expression: '0 9 * * *',
    space_id: null,
    model_override: null,
    enabled: true,
    last_run_at: null,
    last_run_status: null,
    runs: [],
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
    ...overrides,
  };
}

export function makeDashboard(overrides: Record<string, unknown> = {}) {
  return {
    pending_approvals: 0,
    open_task_count: 3,
    active_conversations: 1,
    unread_notifications: 2,
    total_spaces: 2,
    ...overrides,
  };
}

export function makeLayout(widgets: Record<string, unknown>[] = []) {
  return {
    widgets: widgets.length > 0 ? widgets : [
      {
        id: 'widget-kanban',
        widget_type: 'kanban_board',
        position: 0,
        size: 'full',
        config: {
          board_enabled: true,
          board_columns: ['idea', 'scoping', 'todo', 'in_progress', 'done'],
        },
      },
    ],
  };
}

// ─── Full mock setup ─────────────────────────────────────────────────────────

export interface MockDataSet {
  spaces?: Record<string, unknown>[];
  agents?: Record<string, unknown>[];
  items?: Record<string, unknown>[];
  conversations?: Record<string, unknown>[];
  automations?: Record<string, unknown>[];
  dashboard?: Record<string, unknown>;
  layout?: Record<string, unknown>;
  backupStatus?: Record<string, unknown>;
}

/**
 * Intercept all API calls and return mock data.
 * Call this at the start of each test (or in beforeEach).
 */
export async function mockAllAPIs(page: Page, data: MockDataSet = {}) {
  const spaces = data.spaces ?? [];
  const agents = data.agents ?? [];
  const items = data.items ?? [];
  const conversations = data.conversations ?? [];
  const automations = data.automations ?? [];
  const dashboard = data.dashboard ?? makeDashboard({ total_spaces: spaces.length });
  const layout = data.layout ?? makeLayout();
  const backupStatus = data.backupStatus ?? { needs_backup: false, hours_since_backup: 1 };

  // Dashboard
  await page.route('**/api/v1/home/dashboard', (route) =>
    route.fulfill({ json: dashboard }),
  );

  // Spaces (match with and without query params)
  await page.route(/\/api\/v1\/spaces(\?.*)?$/, (route) => {
    // Don't match sub-paths like /spaces/{id} or /spaces/{id}/layout
    const url = route.request().url();
    const path = new URL(url).pathname;
    if (path !== '/api/v1/spaces') return route.fallback();

    if (route.request().method() === 'POST') {
      const newSpace = makeSpace({ name: 'New Space' });
      spaces.push(newSpace);
      return route.fulfill({ json: newSpace, status: 201 });
    }
    return route.fulfill({ json: spaces });
  });

  // Single space
  await page.route('**/api/v1/spaces/*/layout', (route) =>
    route.fulfill({ json: layout }),
  );

  await page.route('**/api/v1/spaces/*/field-schema', (route) =>
    route.fulfill({ json: [] }),
  );

  await page.route(/\/api\/v1\/spaces\/[^/]+$/, (route) => {
    const url = route.request().url();
    const spaceId = url.split('/spaces/')[1]?.split('?')[0];
    const space = spaces.find((s: Record<string, unknown>) => s.id === spaceId);
    if (space) {
      return route.fulfill({ json: space });
    }
    return route.fulfill({ status: 404, json: { detail: 'Not found' } });
  });

  // Items (match with and without query params)
  await page.route(/\/api\/v1\/items(\?.*)?$/, (route) => {
    const url = route.request().url();
    const path = new URL(url).pathname;
    if (path !== '/api/v1/items') return route.fallback();

    if (route.request().method() === 'POST') {
      const newItem = makeItem({ title: 'New Item', space_id: 'space-1' });
      items.push(newItem);
      return route.fulfill({ json: newItem, status: 201 });
    }
    return route.fulfill({ json: items });
  });

  await page.route(/\/api\/v1\/items\/[^/]+\/events/, (route) =>
    route.fulfill({ json: [] }),
  );

  await page.route(/\/api\/v1\/items\/[^/]+\/children/, (route) =>
    route.fulfill({ json: { child_records: [], linked_items: [] } }),
  );

  await page.route(/\/api\/v1\/items\/[^/]+\/move/, (route) => {
    return route.fulfill({ json: { ok: true } });
  });

  await page.route(/\/api\/v1\/items\/[^/]+$/, (route) => {
    const url = route.request().url();
    const itemId = url.split('/items/')[1]?.split('?')[0];
    const item = items.find((i: Record<string, unknown>) => i.id === itemId);
    if (route.request().method() === 'PATCH') {
      return route.fulfill({ json: item ?? {} });
    }
    if (item) {
      return route.fulfill({ json: item });
    }
    return route.fulfill({ status: 404, json: { detail: 'Not found' } });
  });

  // Agents (match with and without query params)
  await page.route(/\/api\/v1\/agents(\?.*)?$/, (route) => {
    const url = route.request().url();
    const path = new URL(url).pathname;
    if (path !== '/api/v1/agents') return route.fallback();

    if (route.request().method() === 'POST') {
      const newAgent = makeAgent({ name: 'New Agent' });
      agents.push(newAgent);
      return route.fulfill({ json: newAgent, status: 201 });
    }
    return route.fulfill({ json: agents });
  });

  await page.route(/\/api\/v1\/agents\/[^/]+$/, (route) => {
    const url = route.request().url();
    const agentId = url.split('/agents/')[1]?.split('?')[0];
    if (route.request().method() === 'DELETE') {
      const idx = agents.findIndex((a: Record<string, unknown>) => a.id === agentId);
      if (idx !== -1) agents.splice(idx, 1);
      return route.fulfill({ status: 204, body: '' });
    }
    if (route.request().method() === 'PATCH') {
      const agent = agents.find((a: Record<string, unknown>) => a.id === agentId);
      return route.fulfill({ json: agent ?? {} });
    }
    const agent = agents.find((a: Record<string, unknown>) => a.id === agentId);
    if (agent) return route.fulfill({ json: agent });
    return route.fulfill({ status: 404, json: { detail: 'Not found' } });
  });

  // Conversations (match with and without query params)
  await page.route(/\/api\/v1\/conversations(\?.*)?$/, (route) => {
    const url = route.request().url();
    const path = new URL(url).pathname;
    if (path !== '/api/v1/conversations') return route.fallback();

    if (route.request().method() === 'POST') {
      const newConv = makeConversation({ name: 'New Convo' });
      conversations.push(newConv);
      return route.fulfill({ json: newConv, status: 201 });
    }
    return route.fulfill({ json: conversations });
  });

  await page.route(/\/api\/v1\/conversations\/[^/]+$/, (route) => {
    const url = route.request().url();
    const convId = url.split('/conversations/')[1]?.split('?')[0];
    const conv = conversations.find((c: Record<string, unknown>) => c.id === convId);
    if (conv) return route.fulfill({ json: conv });
    return route.fulfill({ status: 404, json: { detail: 'Not found' } });
  });

  // Automations (match with and without query params)
  await page.route(/\/api\/v1\/automations(\?.*)?$/, (route) => {
    const url = route.request().url();
    const path = new URL(url).pathname;
    if (path !== '/api/v1/automations') return route.fallback();

    if (route.request().method() === 'POST') {
      const newAuto = makeAutomation({ name: 'New Automation' });
      automations.push(newAuto);
      return route.fulfill({ json: newAuto, status: 201 });
    }
    return route.fulfill({ json: automations });
  });

  await page.route(/\/api\/v1\/automations\/[^/]+\/runs/, (route) =>
    route.fulfill({ json: [] }),
  );

  await page.route(/\/api\/v1\/automations\/[^/]+\/trigger/, (route) =>
    route.fulfill({ json: { ok: true } }),
  );

  await page.route(/\/api\/v1\/automations\/[^/]+$/, (route) => {
    const url = route.request().url();
    const autoId = url.split('/automations/')[1]?.split('?')[0];
    if (route.request().method() === 'DELETE') {
      const idx = automations.findIndex((a: Record<string, unknown>) => a.id === autoId);
      if (idx !== -1) automations.splice(idx, 1);
      return route.fulfill({ status: 204, body: '' });
    }
    if (route.request().method() === 'PATCH') {
      const auto = automations.find((a: Record<string, unknown>) => a.id === autoId);
      if (auto) {
        // Toggle enabled
        try {
          const body = route.request().postDataJSON();
          if (body?.enabled !== undefined) {
            (auto as Record<string, unknown>).enabled = body.enabled;
          }
        } catch { /* ignore */ }
      }
      return route.fulfill({ json: auto ?? {} });
    }
    const auto = automations.find((a: Record<string, unknown>) => a.id === autoId);
    if (auto) return route.fulfill({ json: auto });
    return route.fulfill({ status: 404, json: { detail: 'Not found' } });
  });

  // Backup status
  await page.route('**/api/v1/system/backup-status', (route) =>
    route.fulfill({ json: backupStatus }),
  );

  // Odin
  await page.route('**/api/v1/odin/message', (route) =>
    route.fulfill({ json: { ok: true } }),
  );

  // Search
  await page.route('**/api/v1/search**', (route) => {
    const url = new URL(route.request().url());
    const q = url.searchParams.get('q') ?? '';
    if (!q.trim()) {
      return route.fulfill({ json: { query: q, total_count: 0, results: {} } });
    }
    return route.fulfill({
      json: {
        query: q,
        total_count: 1,
        results: {
          messages: [
            {
              id: 'sr-1',
              type: 'message',
              title: `Result for "${q}"`,
              excerpt: `This is a <mark>${q}</mark> result excerpt`,
              space_id: 'space-1',
              space_name: 'Test Space',
              relevance_score: 0.95,
              created_at: '2026-03-30T10:00:00Z',
              source_id: 'conv-1',
            },
          ],
        },
      },
    });
  });

  // SSE endpoint -- just hang
  await page.route('**/api/v1/sse**', (route) =>
    route.abort('connectionreset'),
  );

  // Notifications
  await page.route('**/api/v1/notifications**', (route) =>
    route.fulfill({ json: [] }),
  );

  // Memory
  await page.route('**/api/v1/memory**', (route) =>
    route.fulfill({ json: [] }),
  );
}
