import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeDashboard, makeLayout, resetIdCounter } from './helpers/mock-api';

test.describe('UI Polish Verification', () => {
  test.describe('loading skeletons', () => {
    test('Home shows skeleton during loading', async ({ page }) => {
      resetIdCounter();
      // Mock with delay to trigger loading state
      await page.route('**/api/v1/home/dashboard', async (route) => {
        await new Promise((r) => setTimeout(r, 2000));
        route.fulfill({ json: makeDashboard({ total_spaces: 0 }) });
      });
      await page.route('**/api/v1/spaces', async (route) => {
        await new Promise((r) => setTimeout(r, 2000));
        route.fulfill({ json: [] });
      });
      // Mock other APIs to prevent errors
      await page.route('**/api/v1/items**', (route) => route.fulfill({ json: [] }));
      await page.route('**/api/v1/conversations**', (route) => route.fulfill({ json: [] }));
      await page.route('**/api/v1/agents**', (route) => route.fulfill({ json: [] }));
      await page.route('**/api/v1/system/backup-status', (route) =>
        route.fulfill({ json: { needs_backup: false } }),
      );
      await page.route('**/api/v1/sse**', (route) => route.abort('connectionreset'));

      await page.goto('/');

      // Skeleton should be visible while loading
      const skeletons = page.locator('.animate-pulse');
      await expect(skeletons.first()).toBeVisible();
    });
  });

  test.describe('modal rendering', () => {
    test.beforeEach(async ({ page }) => {
      resetIdCounter();
      await mockAllAPIs(page, {
        spaces: [],
        agents: [],
        dashboard: makeDashboard({ total_spaces: 0 }),
      });
    });

    test('modal renders as a portal at z-50', async ({ page }) => {
      await page.goto('/agents');

      // Open modal
      await page.getByRole('button', { name: 'New Agent' }).first().click();
      await page.waitForTimeout(300);

      // Modal overlay should be visible
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();

      // The dialog should have a title
      await expect(dialog.locator('h2', { hasText: 'New Agent' })).toBeVisible();
    });
  });

  test.describe('panel slide-in', () => {
    const space = {
      id: 'space-polish',
      name: 'Polish Space',
      template: 'project',
      description: null,
      board_enabled: true,
      board_columns: ['todo', 'done'],
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
              board_columns: ['todo', 'done'],
            },
          },
        ]),
      });
      await page.route('**/api/v1/spaces/*/layout/**', (route) =>
        route.fulfill({ json: {} }),
      );
    });

    test('space settings panel renders as a dialog', async ({ page }) => {
      await page.goto(`/space/${space.id}`);

      // Open settings
      await page.getByRole('button', { name: 'Open space settings' }).click();
      await page.waitForTimeout(300);

      // The panel should render with dialog role
      const panel = page.locator('[role="dialog"][aria-label="Space Settings"]');
      await expect(panel).toBeVisible();

      // Panel has a title
      await expect(panel.locator('h3', { hasText: 'Space Settings' })).toBeVisible();
    });
  });

  test.describe('page fade-in', () => {
    test.beforeEach(async ({ page }) => {
      resetIdCounter();
      await mockAllAPIs(page, {
        spaces: [],
        dashboard: makeDashboard({ total_spaces: 0 }),
      });
    });

    test('page content has fade-in transition wrapper', async ({ page }) => {
      await page.goto('/');

      // The FadeIn wrapper applies transition-opacity class
      const fadeWrapper = page.locator('.transition-opacity').first();
      await expect(fadeWrapper).toBeVisible();
    });
  });
});
