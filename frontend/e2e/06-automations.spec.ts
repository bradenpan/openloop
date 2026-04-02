import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeAutomation, makeAgent, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('Automation Management', () => {
  const agent1 = {
    id: 'agent-auto-1',
    name: 'Auto Agent',
    description: 'Agent for automations',
    system_prompt: '',
    default_model: 'sonnet',
    status: 'active',
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z',
  };

  test.describe('with existing automations', () => {
    const auto1 = {
      id: 'auto-1',
      name: 'Daily Digest',
      description: 'Sends a daily summary',
      agent_id: agent1.id,
      instruction: 'Summarize all open tasks',
      trigger_type: 'cron',
      cron_expression: '0 9 * * *',
      space_id: null,
      model_override: null,
      enabled: true,
      last_run_at: '2026-03-29T09:00:00Z',
      last_run_status: 'success',
      runs: [],
      created_at: '2026-03-28T10:00:00Z',
      updated_at: '2026-03-30T10:00:00Z',
    };

    test.beforeEach(async ({ page }) => {
      resetIdCounter();
      await mockAllAPIs(page, {
        agents: [agent1],
        automations: [auto1],
        dashboard: makeDashboard(),
      });
    });

    test('automations page renders with existing automations', async ({ page }) => {
      await page.goto('/automations');
      await expect(page.locator('h1', { hasText: 'Automations' })).toBeVisible();
      await expect(page.getByText('Daily Digest')).toBeVisible();
      await expect(page.getByText('enabled')).toBeVisible();
    });

    test('create new automation', async ({ page }) => {
      await page.goto('/automations');

      await page.getByRole('button', { name: 'New Automation' }).click();

      const modal = page.getByRole('dialog');
      await expect(modal).toBeVisible();
      await expect(modal.locator('h2', { hasText: 'New Automation' })).toBeVisible();

      // Fill name
      await modal.locator('#automation-name').fill('Weekly Report');

      // Select agent
      await modal.locator('#automation-agent').selectOption(agent1.id);

      // Fill instruction
      await modal.locator('#automation-instruction').fill('Generate weekly report');

      // Daily preset should be default
      await expect(modal.getByText('Every day at')).toBeVisible();

      // Switch to weekly preset
      await modal.getByRole('button', { name: 'Weekly' }).click();

      // Submit
      await modal.getByRole('button', { name: 'Create Automation' }).click();
    });

    test('enable/disable toggle is visible', async ({ page }) => {
      await page.goto('/automations');

      // The toggle switch for the automation
      const toggle = page.getByRole('switch', { name: 'Toggle Daily Digest' });
      await expect(toggle).toBeVisible();
      await expect(toggle).toHaveAttribute('aria-checked', 'true');
    });

    test('click automation opens detail panel', async ({ page }) => {
      await page.goto('/automations');

      // Click the automation name area (the button wrapping the info)
      await page.getByText('Daily Digest').click();

      // Detail panel opens
      const panel = page.getByRole('dialog', { name: 'Daily Digest' });
      await expect(panel).toBeVisible();

      // Verify content
      await expect(panel.getByText('Summarize all open tasks')).toBeVisible();
      await expect(panel.getByText('Every day at')).toBeVisible();
    });
  });

  test.describe('empty state', () => {
    test.beforeEach(async ({ page }) => {
      resetIdCounter();
      await mockAllAPIs(page, {
        agents: [agent1],
        automations: [],
        dashboard: makeDashboard(),
      });
    });

    test('shows empty state with no automations', async ({ page }) => {
      await page.goto('/automations');
      await expect(page.locator('h1', { hasText: 'Automations' })).toBeVisible();
      await expect(page.getByText('No automations yet')).toBeVisible();
      await expect(page.getByText('Create a scheduled agent task')).toBeVisible();
    });
  });
});
