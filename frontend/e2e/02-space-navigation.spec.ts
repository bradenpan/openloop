import { test, expect } from '@playwright/test';
import {
  mockAllAPIs,
  makeSpace,
  makeDashboard,
  makeLayout,
  makeItem,
  resetIdCounter,
} from './helpers/mock-api';

test.describe('Space Navigation & Views', () => {
  const space1 = {
    id: 'space-nav-1',
    name: 'Nav Test Space',
    template: 'project',
    description: 'Space for nav tests',
    board_enabled: true,
    board_columns: ['idea', 'scoping', 'todo', 'in_progress', 'done'],
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [space1],
      dashboard: makeDashboard({ total_spaces: 1 }),
      items: [],
      layout: makeLayout([
        {
          id: 'w-kanban',
          widget_type: 'kanban_board',
          position: 0,
          size: 'full',
          config: {
            board_enabled: true,
            board_columns: ['idea', 'scoping', 'todo', 'in_progress', 'done'],
          },
        },
      ]),
    });
  });

  test('space appears in sidebar and navigates correctly', async ({ page }) => {
    await page.goto('/');

    // Space should be in sidebar
    const sidebarLink = page.locator('aside').getByText('Nav Test Space');
    await expect(sidebarLink).toBeVisible();

    // Click space in sidebar
    await sidebarLink.click();

    // Space header renders
    await expect(page.locator('h1', { hasText: 'Nav Test Space' })).toBeVisible();
  });

  test('space view shows widget grid', async ({ page }) => {
    await page.goto(`/space/${space1.id}`);

    // Space header
    await expect(page.locator('h1', { hasText: 'Nav Test Space' })).toBeVisible();

    // Kanban board widget renders
    await expect(page.locator('h3', { hasText: 'Board' })).toBeVisible();
  });

  test('direct navigation to space URL works', async ({ page }) => {
    await page.goto(`/space/${space1.id}`);
    await expect(page.locator('h1', { hasText: 'Nav Test Space' })).toBeVisible();
  });
});
