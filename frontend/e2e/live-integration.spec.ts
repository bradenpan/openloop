/**
 * Live integration test — runs against the actual backend (http://localhost:8010)
 * and frontend (http://localhost:5173).
 *
 * Requires both servers to be running with seeded data.
 * Does NOT mock any API calls.
 */
import { test, expect } from '@playwright/test';

test.describe('Live Integration', () => {
  test('home page loads and dashboard renders', async ({ page }) => {
    await page.goto('/');

    // Wait for dashboard to load (stat cards)
    await expect(page.getByText('Open Tasks')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Active Conversations')).toBeVisible();
    await expect(page.getByText('Spaces').first()).toBeVisible();

    // Space list should show seeded spaces
    await expect(page.getByText('Personal').first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText('OpenLoop').first()).toBeVisible();
    await expect(page.getByText('Recruiting').first()).toBeVisible();

    // Tasks section should render
    await expect(page.getByText('Tasks').first()).toBeVisible();
  });

  test('navigate to a space and verify widgets render', async ({ page }) => {
    await page.goto('/');

    // Wait for spaces to load in the sidebar
    const sidebarLink = page.locator('nav').getByText('OpenLoop');
    await expect(sidebarLink).toBeVisible({ timeout: 10_000 });
    await sidebarLink.click();

    // Verify the space page content renders
    // Look for space-specific content: the space name header + tasks/board
    await expect(
      page.locator('h1, h2, [class*="heading"]').getByText('OpenLoop').first()
    ).toBeVisible({ timeout: 10_000 });

    // Tasks should be visible in either the list or board view
    await expect(
      page.getByText('Write API tests', { exact: false }).first()
    ).toBeVisible({ timeout: 5_000 });
  });

  test('Odin bar expands and accepts input', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(1_000);

    // The Odin bar is at the bottom of the page
    // Look for the "Ask Odin anything..." text
    const odinPlaceholder = page.getByText('Ask Odin anything...');
    await expect(odinPlaceholder.first()).toBeVisible({ timeout: 5_000 });

    // Click on "Ask Odin anything..." to expand Odin bar
    await odinPlaceholder.first().click();

    // After expanding, an input field should appear with the same placeholder
    const odinInput = page.locator('input[placeholder="Ask Odin anything..."]');
    await expect(odinInput).toBeVisible({ timeout: 3_000 });

    // Type a message
    await odinInput.fill('Hello Odin');
    await expect(odinInput).toHaveValue('Hello Odin');
  });
});
