import { test, expect } from '@playwright/test';
import {
  mockAllAPIs,
  makeConversation,
  makeAgent,
  makeLayout,
  makeDashboard,
  resetIdCounter,
} from './helpers/mock-api';

test.describe('Conversation Lifecycle', () => {
  const space = {
    id: 'space-conv',
    name: 'Conv Space',
    template: 'project',
    description: null,
    board_enabled: true,
    board_columns: ['idea', 'todo', 'in_progress', 'done'],
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  const agent = {
    id: 'agent-conv-1',
    name: 'Chat Agent',
    description: 'Agent for conversations',
    system_prompt: 'Be helpful',
    default_model: 'sonnet',
    status: 'active',
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  const existingConv = {
    id: 'conv-existing-1',
    name: 'Existing Chat',
    agent_id: agent.id,
    space_id: space.id,
    status: 'active',
    model_override: null,
    session_id: null,
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  const columns = ['idea', 'todo', 'in_progress', 'done'];

  test.beforeEach(async ({ page }) => {
    resetIdCounter();

    const layout = makeLayout([
      {
        id: 'w-kanban',
        widget_type: 'kanban_board',
        position: 0,
        size: 'large',
        config: { board_enabled: true, board_columns: columns },
      },
      {
        id: 'w-conversations',
        widget_type: 'conversation_sidebar',
        position: 1,
        size: 'small',
        config: {},
      },
    ]);

    await mockAllAPIs(page, {
      spaces: [space],
      agents: [agent],
      conversations: [existingConv],
      dashboard: makeDashboard({ total_spaces: 1, active_conversations: 1 }),
      layout,
    });

    // Mock conversation messages
    await page.route(/\/api\/v1\/conversations\/[^/]+\/messages/, (route) =>
      route.fulfill({ json: [] }),
    );
  });

  test('conversation appears in sidebar on Home page', async ({ page }) => {
    await page.goto('/');
    // Recent Conversations section on Home
    await expect(page.locator('h2', { hasText: 'Recent Conversations' })).toBeVisible();
  });

  test('conversation list on Home shows existing conversation', async ({ page }) => {
    await page.goto('/');
    // The conversation list component should render the existing conversation
    await expect(page.getByText('Existing Chat').first()).toBeVisible();
  });
});
