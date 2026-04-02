import { test, expect } from '@playwright/test';
import {
  mockAllAPIs,
  makeItem,
  makeLayout,
  makeDashboard,
  resetIdCounter,
} from './helpers/mock-api';

test.describe('Item CRUD', () => {
  const columns = ['idea', 'scoping', 'todo', 'in_progress', 'done'];

  const space = {
    id: 'space-item-crud',
    name: 'Item CRUD Space',
    template: 'project',
    description: null,
    board_enabled: true,
    board_columns: columns,
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  const existingItem = {
    id: 'item-existing-1',
    space_id: space.id,
    title: 'Existing Task',
    description: 'An existing task',
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
  };

  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [space],
      items: [existingItem],
      dashboard: makeDashboard({ total_spaces: 1, open_task_count: 1 }),
      layout: makeLayout([
        {
          id: 'w-kanban',
          widget_type: 'kanban_board',
          position: 0,
          size: 'full',
          config: { board_enabled: true, board_columns: columns },
        },
      ]),
    });
  });

  test('existing item appears in kanban board', async ({ page }) => {
    await page.goto(`/space/${space.id}`);
    await expect(page.getByText('Existing Task')).toBeVisible();
  });

  test('create item via modal', async ({ page }) => {
    await page.goto(`/space/${space.id}`);

    // Click "+ Add Item" button
    await page.getByRole('button', { name: '+ Add Item' }).first().click();

    // Modal opens
    const modal = page.getByRole('dialog');
    await expect(modal).toBeVisible();
    await expect(modal.locator('h2', { hasText: 'Create Item' })).toBeVisible();

    // Fill title
    await modal.locator('input').first().fill('New Test Item');

    // Submit
    await modal.getByRole('button', { name: 'Create' }).click();
  });

  test('open item detail panel by clicking item card', async ({ page }) => {
    await page.goto(`/space/${space.id}`);

    // Click on the existing item
    await page.getByText('Existing Task').click();

    // Detail panel should open
    const panel = page.getByRole('dialog', { name: 'Item Details' });
    await expect(panel).toBeVisible();

    // Verify title field
    await expect(panel.locator('input').first()).toHaveValue('Existing Task');

    // Close the panel
    await panel.getByRole('button', { name: 'Close panel' }).click();
    await expect(panel).not.toBeVisible();
  });

  test('kanban columns render', async ({ page }) => {
    await page.goto(`/space/${space.id}`);

    // Check column headers exist (uppercase text)
    for (const col of ['idea', 'scoping', 'todo', 'in_progress']) {
      await expect(page.locator(`text=${col}`).first()).toBeVisible();
    }
  });
});
