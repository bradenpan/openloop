import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('Settings', () => {
  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [],
      dashboard: makeDashboard({ total_spaces: 0 }),
    });
  });

  test('settings page renders', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.locator('h1', { hasText: 'Settings' })).toBeVisible();
    await expect(page.locator('h2', { hasText: 'Appearance' })).toBeVisible();
  });

  test('toggle theme changes data-theme attribute', async ({ page }) => {
    await page.goto('/settings');

    // Get initial theme
    const initialTheme = await page.evaluate(() => document.documentElement.dataset.theme);

    // Click toggle button
    await page.getByRole('button', { name: /click to toggle/ }).click();
    await page.waitForTimeout(200);

    // Theme should be different
    const newTheme = await page.evaluate(() => document.documentElement.dataset.theme);
    expect(newTheme).not.toBe(initialTheme);

    // Toggle back
    await page.getByRole('button', { name: /click to toggle/ }).click();
    await page.waitForTimeout(200);

    const restored = await page.evaluate(() => document.documentElement.dataset.theme);
    expect(restored).toBe(initialTheme);
  });

  test('switch palette updates data-palette attribute', async ({ page }) => {
    await page.goto('/settings');

    // Click each palette and verify the attribute changes
    const palettes = ['Slate + Cyan', 'Warm Stone + Amber', 'Neutral + Indigo'];
    const expectedIds = ['slate-cyan', 'warm-amber', 'neutral-indigo'];

    for (let i = 0; i < palettes.length; i++) {
      await page.getByText(palettes[i], { exact: false }).first().click();
      await page.waitForTimeout(200);
      const current = await page.evaluate(() => document.documentElement.dataset.palette);
      expect(current).toBe(expectedIds[i]);
    }
  });

  test('palette persists after page reload', async ({ page }) => {
    await page.goto('/settings');

    // Set to warm-amber
    await page.getByText('Warm Stone + Amber', { exact: false }).first().click();
    await page.waitForTimeout(200);

    const before = await page.evaluate(() => document.documentElement.dataset.palette);
    expect(before).toBe('warm-amber');

    // Reload
    await page.reload();
    await page.waitForLoadState('networkidle');

    const after = await page.evaluate(() => document.documentElement.dataset.palette);
    expect(after).toBe('warm-amber');
  });

  test('navigate to settings via sidebar', async ({ page }) => {
    await page.goto('/');
    await page.locator('aside').getByText('Settings').click();
    await expect(page.locator('h1', { hasText: 'Settings' })).toBeVisible();
  });
});
