import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeLayout, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('Board Workflow (Kanban)', () => {
  const columns = ['idea', 'scoping', 'todo', 'in_progress', 'done'];

  const space = {
    id: 'space-kanban',
    name: 'Kanban Space',
    template: 'project',
    description: null,
    board_enabled: true,
    board_columns: columns,
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  const items = [
    {
      id: 'item-k-1',
      space_id: space.id,
      title: 'Design Homepage',
      description: 'Design the homepage layout',
      item_type: 'task',
      stage: 'idea',
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
    },
    {
      id: 'item-k-2',
      space_id: space.id,
      title: 'Build API',
      description: null,
      item_type: 'task',
      stage: 'in_progress',
      is_done: false,
      archived: false,
      priority: 2,
      due_date: null,
      sort_position: 0,
      is_agent_task: false,
      parent_id: null,
      custom_fields: null,
      created_at: '2026-03-30T10:00:00Z',
      updated_at: '2026-03-30T10:00:00Z',
    },
    {
      id: 'item-k-3',
      space_id: space.id,
      title: 'Write Tests',
      description: null,
      item_type: 'task',
      stage: 'done',
      is_done: true,
      archived: false,
      priority: null,
      due_date: null,
      sort_position: 0,
      is_agent_task: false,
      parent_id: null,
      custom_fields: null,
      created_at: '2026-03-30T10:00:00Z',
      updated_at: '2026-03-30T10:00:00Z',
    },
  ];

  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [space],
      items,
      dashboard: makeDashboard({ total_spaces: 1, open_task_count: 2 }),
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

  test('kanban columns render with items distributed', async ({ page }) => {
    await page.goto(`/space/${space.id}`);

    // Board header
    await expect(page.locator('h3', { hasText: 'Board' })).toBeVisible();

    // Column headers (done is hidden by default)
    for (const col of ['idea', 'scoping', 'todo', 'in_progress']) {
      await expect(page.locator(`text=${col}`).first()).toBeVisible();
    }

    // Items in their columns
    await expect(page.getByText('Design Homepage')).toBeVisible();
    await expect(page.getByText('Build API')).toBeVisible();
  });

  test('done column is hidden by default, toggled with Show done', async ({ page }) => {
    await page.goto(`/space/${space.id}`);

    // Done column should be hidden by default
    // The "Show done" button toggles it
    const showDoneBtn = page.getByText('Show done');
    await expect(showDoneBtn).toBeVisible();

    // "Write Tests" (in done column) should not be visible
    await expect(page.getByText('Write Tests')).not.toBeVisible();

    // Click "Show done"
    await showDoneBtn.click();

    // Now done column and its items should be visible
    await expect(page.getByText('Write Tests')).toBeVisible();

    // Button text changes to "Hide done"
    await expect(page.getByText('Hide done')).toBeVisible();
  });

  test('stage dropdown in item detail panel', async ({ page }) => {
    await page.goto(`/space/${space.id}`);

    // Click on an item to open detail
    await page.getByText('Design Homepage').click();

    // Detail panel opens
    const panel = page.getByRole('dialog', { name: 'Item Details' });
    await expect(panel).toBeVisible();

    // Stage selector should be present
    const stageSelect = panel.locator('select').first();
    await expect(stageSelect).toBeVisible();

    // All columns should be options
    for (const col of columns) {
      await expect(stageSelect.locator(`option[value="${col}"]`)).toBeAttached();
    }
  });

  test('create item from board adds it', async ({ page }) => {
    await page.goto(`/space/${space.id}`);

    // Click + Add Item
    await page.getByRole('button', { name: '+ Add Item' }).first().click();

    const modal = page.getByRole('dialog');
    await expect(modal).toBeVisible();
    await expect(modal.locator('h2', { hasText: 'Create Item' })).toBeVisible();

    // Fill and submit
    await modal.locator('input').first().fill('New Kanban Task');
    await modal.getByRole('button', { name: 'Create' }).click();
  });
});
