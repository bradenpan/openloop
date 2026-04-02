import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('Empty States', () => {
  test.beforeEach(async ({ page }) => {
    resetIdCounter();
    await mockAllAPIs(page, {
      spaces: [],
      agents: [],
      automations: [],
      items: [],
      conversations: [],
      dashboard: makeDashboard({ total_spaces: 0, open_task_count: 0, active_conversations: 0 }),
    });
  });

  test('Home shows welcome card when no spaces', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Welcome to OpenLoop')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create your first space' })).toBeVisible();
  });

  test('Agents page shows empty state', async ({ page }) => {
    await page.goto('/agents');
    await expect(page.getByText('No agents yet.')).toBeVisible();
    await expect(page.getByText('Create an agent to get started.')).toBeVisible();
    // Still has the New Agent button in the header and in the empty state
    const newAgentBtns = page.getByRole('button', { name: 'New Agent' });
    await expect(newAgentBtns.first()).toBeVisible();
  });

  test('Automations page shows empty state', async ({ page }) => {
    await page.goto('/automations');
    await expect(page.getByText('No automations yet')).toBeVisible();
    await expect(page.getByText('Create a scheduled agent task to get started.')).toBeVisible();
  });
});
