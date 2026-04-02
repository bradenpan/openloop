import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('Keyboard Shortcuts', () => {
  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [],
      dashboard: makeDashboard({ total_spaces: 0 }),
    });
  });

  test('/ focuses Odin input', async ({ page }) => {
    await page.goto('/');
    // Wait for page to settle and focus to not be in any input
    await page.waitForTimeout(500);

    // Click body to ensure no input is focused
    await page.locator('main').click();
    await page.waitForTimeout(200);

    // Press /
    await page.keyboard.press('/');
    await page.waitForTimeout(500);

    // Odin should expand and input should be visible
    const odinInput = page.locator('[data-odin-input]');
    await expect(odinInput).toBeVisible();
    await expect(odinInput).toBeFocused();
  });

  test('? toggles shortcuts help overlay', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);

    // Click body to ensure no input is focused
    await page.locator('main').click();
    await page.waitForTimeout(200);

    // Press ? (Shift+/)
    await page.keyboard.press('?');
    await page.waitForTimeout(300);

    // Shortcuts overlay should appear
    const overlay = page.locator('[role="dialog"][aria-label="Keyboard shortcuts"]');
    await expect(overlay).toBeVisible();
    await expect(overlay.getByText('Focus Odin input')).toBeVisible();
    await expect(overlay.getByText('Open search')).toBeVisible();

    // Press Escape to close
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    await expect(overlay).not.toBeVisible();
  });

  test('Escape closes shortcuts overlay', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);

    // Click body to ensure no input is focused
    await page.locator('main').click();
    await page.waitForTimeout(200);

    // Open shortcuts help
    await page.keyboard.press('?');
    await page.waitForTimeout(300);

    const overlay = page.locator('[role="dialog"][aria-label="Keyboard shortcuts"]');
    await expect(overlay).toBeVisible();

    // Escape closes it
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    await expect(overlay).not.toBeVisible();
  });
});
