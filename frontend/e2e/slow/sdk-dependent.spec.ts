/**
 * SDK-dependent tests — require a running backend with real database.
 * These are marked as slow and skipped by default.
 *
 * Run with: npx playwright test e2e/slow --project=chromium
 * These tests expect:
 *   - Backend running on localhost:8010
 *   - Frontend running on localhost:5173
 */
import { test, expect } from '@playwright/test';

// Skip all tests in this file by default — run explicitly with --grep @slow
test.describe('Memory Lifecycle (slow)', { tag: '@slow' }, () => {
  test.skip(true, 'Requires running backend with Claude SDK — run explicitly');

  test('create facts via API and trigger consolidation', async ({ page }) => {
    // This would:
    // 1. POST facts to /api/v1/memory with a real backend
    // 2. Trigger consolidation
    // 3. Verify report returned
    await page.goto('/');
    // Implementation would use fetch() to hit real API endpoints
  });
});

test.describe('Summary Consolidation (slow)', { tag: '@slow' }, () => {
  test.skip(true, 'Requires running backend with Claude SDK — run explicitly');

  test('create 20+ summaries and trigger consolidation', async ({ page }) => {
    // This would:
    // 1. Create many conversation summaries via API
    // 2. Trigger consolidation endpoint
    // 3. Verify meta-summary created
    await page.goto('/');
  });
});

test.describe('Cross-Space Search (slow)', { tag: '@slow' }, () => {
  test.skip(true, 'Requires running backend with Claude SDK — run explicitly');

  test('search returns results across multiple spaces', async ({ page }) => {
    // This would:
    // 1. Create content in two different spaces via API
    // 2. Use the search modal (Ctrl+K) to search
    // 3. Verify results from both spaces appear
    await page.goto('/');
    await page.keyboard.press('Control+k');

    const modal = page.getByRole('dialog', { name: 'Search' });
    await expect(modal).toBeVisible();
  });
});
