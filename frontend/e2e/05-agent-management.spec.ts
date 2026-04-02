import { test, expect } from '@playwright/test';
import { mockAllAPIs, makeDashboard, resetIdCounter } from './helpers/mock-api';

test.describe('Agent Management', () => {
  test.describe('with existing agents', () => {
    const agent1 = {
      id: 'agent-mgmt-1',
      name: 'Research Agent',
      description: 'Helps with research',
      system_prompt: 'You research topics.',
      default_model: 'sonnet',
      status: 'active',
      created_at: '2026-03-30T10:00:00Z',
      updated_at: '2026-03-30T10:00:00Z',
    };

    test.beforeEach(async ({ page }) => {
      resetIdCounter();
      await mockAllAPIs(page, {
        agents: [agent1],
        dashboard: makeDashboard(),
      });
    });

    test('agents page renders with existing agents', async ({ page }) => {
      await page.goto('/agents');
      await expect(page.locator('h1', { hasText: 'Agents' })).toBeVisible();
      await expect(page.getByText('Research Agent')).toBeVisible();
      await expect(page.getByRole('button', { name: 'New Agent' })).toBeVisible();
    });

    test('create a new agent', async ({ page }) => {
      await page.goto('/agents');

      await page.getByRole('button', { name: 'New Agent' }).click();

      const modal = page.getByRole('dialog');
      await expect(modal).toBeVisible();
      await expect(modal.locator('h2', { hasText: 'New Agent' })).toBeVisible();

      // Fill form
      await modal.locator('input').first().fill('Build Agent');
      await modal.locator('select').selectOption('opus');

      // Submit
      await modal.getByRole('button', { name: 'Create Agent' }).click();
    });

    test('edit agent opens pre-populated form', async ({ page }) => {
      await page.goto('/agents');

      // Click Edit button using aria-label
      await page.locator(`button[aria-label="Edit Research Agent"]`).click();

      const modal = page.getByRole('dialog');
      await expect(modal).toBeVisible();
      await expect(modal.locator('h2', { hasText: 'Edit Agent' })).toBeVisible();

      // Verify pre-populated name
      await expect(modal.locator('input').first()).toHaveValue('Research Agent');

      // Close modal
      await modal.getByRole('button', { name: 'Close' }).click();
      await expect(modal).not.toBeVisible();
    });

    test('delete agent flow', async ({ page }) => {
      await page.goto('/agents');

      // Click Delete button using aria-label
      await page.locator(`button[aria-label="Delete Research Agent"]`).click();

      // Confirm dialog
      const modal = page.getByRole('dialog');
      await expect(modal).toBeVisible();
      await expect(modal.locator('h2', { hasText: 'Delete Agent' })).toBeVisible();
      await expect(modal.getByText('Research Agent')).toBeVisible();

      // Click Delete
      await modal.getByRole('button', { name: 'Delete' }).click();
    });
  });

  test.describe('empty state', () => {
    test.beforeEach(async ({ page }) => {
      resetIdCounter();
      await mockAllAPIs(page, {
        agents: [],
        dashboard: makeDashboard(),
      });
    });

    test('agents page shows empty state', async ({ page }) => {
      await page.goto('/agents');
      await expect(page.locator('h1', { hasText: 'Agents' })).toBeVisible();
      await expect(page.getByText('No agents yet.')).toBeVisible();
      await expect(page.getByText('Create an agent to get started.')).toBeVisible();
    });
  });
});
