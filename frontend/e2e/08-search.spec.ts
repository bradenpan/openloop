import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('Search', () => {
  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [],
      dashboard: makeDashboard({ total_spaces: 0 }),
    });
  });

  test('Ctrl+K opens search modal', async ({ page }) => {
    await page.goto('/');
    // Wait for page to settle
    await page.waitForTimeout(500);

    // Press Ctrl+K
    await page.keyboard.press('Control+k');
    await page.waitForTimeout(300);

    // Modal opens -- find it by the search input placeholder
    const searchInput = page.locator('input[placeholder*="Search conversations"]');
    await expect(searchInput).toBeVisible();
  });

  test('type query and see results', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);

    await page.keyboard.press('Control+k');
    await page.waitForTimeout(300);

    const searchInput = page.locator('input[placeholder*="Search conversations"]');
    await expect(searchInput).toBeVisible();

    // Type a query
    await searchInput.fill('test query');

    // Wait for debounced search
    await page.waitForTimeout(500);

    // Results should appear
    await expect(page.getByText('Result for "test query"')).toBeVisible();
  });

  test('Escape closes search modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);

    await page.keyboard.press('Control+k');
    await page.waitForTimeout(300);

    const searchInput = page.locator('input[placeholder*="Search conversations"]');
    await expect(searchInput).toBeVisible();

    // Press Escape inside the modal
    await searchInput.press('Escape');
    await page.waitForTimeout(300);

    // Modal should close
    await expect(searchInput).not.toBeVisible();
  });

  test('empty search shows placeholder text', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);

    // Click body first to ensure nothing is focused
    await page.locator('main').click();
    await page.waitForTimeout(200);

    await page.keyboard.press('Control+k');

    // Wait for search input to be visible
    const searchInput = page.locator('input[placeholder*="Search conversations"]');
    await expect(searchInput).toBeVisible({ timeout: 5000 });

    await expect(page.getByText('Start typing to search')).toBeVisible();
  });

  test('clicking sidebar Search button opens modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForTimeout(500);

    // Click the search button in sidebar
    const searchBtn = page.locator('aside button[title*="Search"]');
    await searchBtn.click();
    await page.waitForTimeout(300);

    const searchInput = page.locator('input[placeholder*="Search conversations"]');
    await expect(searchInput).toBeVisible();
  });
});
