import { test, expect } from '@playwright/test';
import {
  mockAllAPIs,
  makeDashboard,
  resetIdCounter,
} from './helpers/mock-api';

test.describe('Home Dashboard', () => {
  const space1 = {
    id: 'space-dash-1',
    name: 'Dashboard Space',
    template: 'project',
    description: 'A project space',
    board_enabled: true,
    board_columns: ['todo', 'done'],
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  const agent1 = {
    id: 'agent-dash-1',
    name: 'Dashboard Agent',
    description: 'Agent for dashboard',
    system_prompt: '',
    default_model: 'sonnet',
    status: 'active',
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  const task1 = {
    id: 'task-dash-1',
    space_id: space1.id,
    title: 'Write Documentation',
    description: null,
    item_type: 'task',
    stage: 'todo',
    is_done: false,
    archived: false,
    priority: 1,
    due_date: null,
    sort_position: 0,
    is_agent_task: false,
    parent_id: null,
    custom_fields: null,
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  const conv1 = {
    id: 'conv-dash-1',
    name: 'Dashboard Chat',
    agent_id: agent1.id,
    space_id: space1.id,
    status: 'active',
    model_override: null,
    session_id: null,
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [space1],
      agents: [agent1],
      items: [task1],
      conversations: [conv1],
      dashboard: makeDashboard({
        total_spaces: 1,
        open_task_count: 1,
        active_conversations: 1,
        pending_approvals: 0,
        unread_notifications: 3,
      }),
    });
  });

  test('stat cards render with labels', async ({ page }) => {
    await page.goto('/');

    // Wait for dashboard to load
    await page.waitForTimeout(500);

    // Stat card labels
    await expect(page.getByText('Pending Approvals')).toBeVisible();
    await expect(page.getByText('Open Tasks')).toBeVisible();
    await expect(page.getByText('Active Conversations')).toBeVisible();
    await expect(page.getByText('Unread Notifications')).toBeVisible();
  });

  test('space list renders space cards', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);

    await expect(page.locator('h2', { hasText: 'Spaces' })).toBeVisible();
    await expect(page.getByText('Dashboard Space').first()).toBeVisible();
  });

  test('tasks section renders', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h2', { hasText: 'Tasks' })).toBeVisible();
  });

  test('conversations section renders', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);
    await expect(page.locator('h2', { hasText: 'Recent Conversations' })).toBeVisible();
    await expect(page.getByText('Dashboard Chat').first()).toBeVisible();
  });

  test('create space button is visible in space list', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);
    await expect(page.getByText('Create Space').first()).toBeVisible();
  });

  test('space card has cursor-pointer for clickability', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);

    // Find the space card
    const spaceCard = page.locator('h3', { hasText: 'Dashboard Space' });
    await expect(spaceCard).toBeVisible();

    // The parent Card has cursor-pointer class indicating it is interactive
    const card = spaceCard.locator('xpath=ancestor::div[contains(@class,"cursor-pointer")]');
    await expect(card.first()).toBeVisible();
  });
});

test.describe('Home Dashboard - backup reminder', () => {
  test('shows backup reminder when needs_backup is true', async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [],
      dashboard: makeDashboard({ total_spaces: 0 }),
      backupStatus: { needs_backup: true, hours_since_backup: 72 },
    });

    await page.goto('/');
    await page.waitForTimeout(500);
    await expect(page.getByText(/No backup in.*day/)).toBeVisible();
  });
});
