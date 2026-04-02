import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeLayout, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('Space Settings Panel', () => {
  const space = {
    id: 'space-settings',
    name: 'Settings Space',
    template: 'project',
    description: 'Testing space settings',
    board_enabled: true,
    board_columns: ['todo', 'in_progress', 'done'],
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [space],
      items: [],
      dashboard: makeDashboard({ total_spaces: 1 }),
      layout: makeLayout([
        {
          id: 'w-kanban',
          widget_type: 'kanban_board',
          position: 0,
          size: 'full',
          config: {
            board_enabled: true,
            board_columns: ['todo', 'in_progress', 'done'],
          },
        },
      ]),
    });

    // Mock layout update endpoints
    await page.route('**/api/v1/spaces/*/layout/**', (route) =>
      route.fulfill({ json: {} }),
    );
  });

  test('gear icon opens Space Settings panel', async ({ page }) => {
    await page.goto(`/space/${space.id}`);

    // Click gear icon
    await page.getByRole('button', { name: 'Open space settings' }).click();

    // Panel should open
    const panel = page.getByRole('dialog', { name: 'Space Settings' });
    await expect(panel).toBeVisible();
  });

  test('Space Settings has Layout, Memory, History tabs', async ({ page }) => {
    await page.goto(`/space/${space.id}`);
    await page.getByRole('button', { name: 'Open space settings' }).click();

    const panel = page.getByRole('dialog', { name: 'Space Settings' });
    await expect(panel).toBeVisible();

    // Tab buttons
    await expect(panel.getByText('Layout')).toBeVisible();
    await expect(panel.getByText('Memory')).toBeVisible();
    await expect(panel.getByText('History')).toBeVisible();
  });

  test('switch between tabs', async ({ page }) => {
    await page.goto(`/space/${space.id}`);
    await page.getByRole('button', { name: 'Open space settings' }).click();

    const panel = page.getByRole('dialog', { name: 'Space Settings' });

    // Click Memory tab
    await panel.getByText('Memory').click();
    // Memory tab content should render (it fetches memory data)

    // Click History tab
    await panel.getByText('History').click();
    // History tab shows placeholder
    await expect(panel.getByText('Conversation history consolidation')).toBeVisible();

    // Click back to Layout
    await panel.getByText('Layout').click();
  });

  test('close Space Settings panel', async ({ page }) => {
    await page.goto(`/space/${space.id}`);
    await page.getByRole('button', { name: 'Open space settings' }).click();

    const panel = page.getByRole('dialog', { name: 'Space Settings' });
    await expect(panel).toBeVisible();

    // Close via button
    await panel.getByRole('button', { name: 'Close panel' }).click();
    await expect(panel).not.toBeVisible();
  });
});
