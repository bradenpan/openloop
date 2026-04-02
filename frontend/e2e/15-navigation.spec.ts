import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('App Shell & Navigation', () => {
  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [],
      agents: [],
      dashboard: makeDashboard({ total_spaces: 0 }),
    });
  });

  test('sidebar renders with branding and navigation links', async ({ page }) => {
    await page.goto('/');

    // Sidebar
    const sidebar = page.locator('aside').first();
    await expect(sidebar).toBeVisible();

    // Branding
    await expect(sidebar.getByText('OpenLoop')).toBeVisible();

    // Navigation links
    await expect(sidebar.getByText('Home')).toBeVisible();
    await expect(sidebar.getByText('Spaces', { exact: true })).toBeVisible();
    await expect(sidebar.getByText('Agents')).toBeVisible();
    await expect(sidebar.getByText('Automations')).toBeVisible();
    await expect(sidebar.getByText('Settings')).toBeVisible();
  });

  test('sidebar collapse and expand', async ({ page }) => {
    await page.goto('/');

    // Collapse sidebar
    await page.getByRole('button', { name: 'Collapse sidebar' }).click();
    await page.waitForTimeout(300);

    // Sidebar should be narrow
    const sidebar = page.locator('aside').first();
    const box = await sidebar.boundingBox();
    expect(box!.width).toBeLessThan(60);

    // Expand sidebar
    await page.getByRole('button', { name: 'Open sidebar' }).click();
    await page.waitForTimeout(300);

    const expandedBox = await sidebar.boundingBox();
    expect(expandedBox!.width).toBeGreaterThan(150);
  });

  test('navigate between pages via sidebar', async ({ page }) => {
    await page.goto('/');

    // Go to Agents
    await page.locator('aside').getByText('Agents').click();
    await expect(page.locator('h1', { hasText: 'Agents' })).toBeVisible();
    await expect(page).toHaveURL(/\/agents/);

    // Go to Settings
    await page.locator('aside').getByText('Settings').click();
    await expect(page.locator('h1', { hasText: 'Settings' })).toBeVisible();
    await expect(page).toHaveURL(/\/settings/);

    // Go to Automations
    await page.locator('aside').getByText('Automations').click();
    await expect(page.locator('h1', { hasText: 'Automations' })).toBeVisible();
    await expect(page).toHaveURL(/\/automations/);

    // Go Home
    await page.locator('aside nav').getByText('Home').click();
    await expect(page).toHaveURL('/');
  });

  test('browser back and forward work', async ({ page }) => {
    await page.goto('/');

    // Navigate to Agents
    await page.locator('aside').getByText('Agents').click();
    await expect(page).toHaveURL(/\/agents/);

    // Navigate to Settings
    await page.locator('aside').getByText('Settings').click();
    await expect(page).toHaveURL(/\/settings/);

    // Back should go to Agents
    await page.goBack();
    await expect(page).toHaveURL(/\/agents/);

    // Forward should go to Settings
    await page.goForward();
    await expect(page).toHaveURL(/\/settings/);
  });

  test('Odin bar renders', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Ask Odin anything...').first()).toBeVisible();
    await expect(page.getByText('Opus').first()).toBeVisible();
  });

  test('Odin bar expand and collapse', async ({ page }) => {
    await page.goto('/');

    // Click expand button
    await page.getByRole('button', { name: 'Expand Odin' }).click();
    await page.waitForTimeout(300);

    // Chat input should be visible
    const odinInput = page.locator('[data-odin-input]');
    await expect(odinInput).toBeVisible();

    // Collapse
    await page.getByRole('button', { name: 'Collapse Odin' }).click();
    await page.waitForTimeout(300);

    // "Ask Odin anything..." text button should be back
    await expect(page.locator('button', { hasText: 'Ask Odin anything...' })).toBeVisible();
  });
});
