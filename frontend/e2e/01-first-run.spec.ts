import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('First-Run Experience', () => {
  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    // Mock with zero spaces to trigger first-run state
    await mockAllAPIs(page, {
      spaces: [],
      dashboard: makeDashboard({ total_spaces: 0 }),
    });
  });

  test('shows welcome card when no spaces exist', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=Welcome to OpenLoop')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create your first space' })).toBeVisible();
  });

  test('create space via welcome card modal', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=Welcome to OpenLoop')).toBeVisible();

    // Click the welcome card button
    await page.getByRole('button', { name: 'Create your first space' }).click();

    // Modal opens
    const modal = page.getByRole('dialog');
    await expect(modal).toBeVisible();
    await expect(modal.locator('h2', { hasText: 'Create Space' })).toBeVisible();

    // Fill in name
    await modal.locator('input').first().fill('My First Space');

    // Select Project template (should be default)
    await expect(modal.getByText('Project', { exact: false }).first()).toBeVisible();

    // Click Create Space button
    await modal.getByRole('button', { name: 'Create Space' }).click();
  });

  test('empty Home sections render headings', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h2', { hasText: 'Active Agents' })).toBeVisible();
    await expect(page.locator('h2', { hasText: 'Spaces' })).toBeVisible();
    await expect(page.locator('h2', { hasText: 'Tasks' })).toBeVisible();
    await expect(page.locator('h2', { hasText: 'Recent Conversations' })).toBeVisible();
  });
});
