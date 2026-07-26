import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.__mockEvaluateCalls = 0;
    window.__mockStopCalls = 0;
    window.__mockEvaluateError = null;

    if (!customElements.get('strudel-editor')) {
      customElements.define(
        'strudel-editor',
        class MockStrudelEditor extends HTMLElement {
          editor: any;
          private textarea!: HTMLTextAreaElement;

          connectedCallback() {
            const host = document.createElement('div');
            host.dataset.testid = 'mock-repl-host';
            host.style.height = '100%';

            this.textarea = document.createElement('textarea');
            this.textarea.dataset.testid = 'mock-editor';
            this.textarea.style.width = '100%';
            this.textarea.style.height = '100%';
            host.append(this.textarea);
            this.after(host);

            const element = this;
            this.textarea.addEventListener('input', () => {
              element.dispatchEvent(new Event('update'));
            });

            this.editor = {
              get code() {
                return element.textarea.value;
              },
              setCode(code: string) {
                element.textarea.value = code;
                element.dispatchEvent(new Event('update'));
              },
              async evaluate() {
                window.__mockEvaluateCalls += 1;
                if (window.__mockEvaluateError) {
                  throw new Error(window.__mockEvaluateError);
                }
              },
              async stop() {
                window.__mockStopCalls += 1;
              },
              getCursorLocation() {
                return element.textarea.selectionStart;
              },
              editor: {
                state: {
                  doc: { toString: () => element.textarea.value },
                  selection: { main: { from: 0, to: 0 } },
                  sliceDoc: (from: number, to: number) => element.textarea.value.slice(from, to),
                },
              },
            };
          }
        },
      );
    }
  });
});

test('evaluate success saves track and creates snapshot', async ({ page }) => {
  const trackRequests: string[] = [];
  const snapshotRequests: string[] = [];
  page.on('request', async (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/track')) {
      trackRequests.push(request.postData() ?? '');
    }
    if (request.method() === 'POST' && request.url().endsWith('/snapshots')) {
      snapshotRequests.push(request.postData() ?? '');
    }
  });

  await page.goto('/');
  await expect(page.getByTestId('mock-editor')).toHaveValue(/bd/);
  await page.getByTestId('mock-editor').fill('s("bd*4")');
  await page.getByRole('button', { name: 'Evaluate' }).click();

  await expect(page.locator('#status')).toContainText('Playing');
  await expect.poll(() => trackRequests.length).toBe(1);
  await expect.poll(() => snapshotRequests.length).toBe(1);
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(1);
});

test('evaluate failure does not save track or snapshot', async ({ page }) => {
  const trackRequests: string[] = [];
  const snapshotRequests: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/track')) {
      trackRequests.push(request.postData() ?? '');
    }
    if (request.method() === 'POST' && request.url().endsWith('/snapshots')) {
      snapshotRequests.push(request.postData() ?? '');
    }
  });

  await page.goto('/');
  await page.evaluate(() => {
    window.__mockEvaluateError = 'mock evaluate failed';
  });
  await page.getByTestId('mock-editor').fill('broken(');
  await page.getByRole('button', { name: 'Evaluate' }).click();

  await expect(page.locator('#status')).toContainText('mock evaluate failed');
  expect(trackRequests).toHaveLength(0);
  expect(snapshotRequests).toHaveLength(0);
});

test('dirty editor ignores remote track updates', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('mock-editor').fill('s("local edit")');

  await page.request.post('/track', { data: { code: 's("remote edit")' } });

  await expect(page.locator('#status')).toContainText('unsaved changes');
  await expect(page.getByTestId('mock-editor')).toHaveValue('s("local edit")');
});

test('revert restores the last successful evaluation', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('mock-editor').fill('s("bd*4")');
  await page.getByRole('button', { name: 'Evaluate' }).click();
  await expect(page.locator('#status')).toContainText('Playing');

  await page.getByTestId('mock-editor').fill('s("bad idea")');
  await expect(page.locator('#revert-last-good')).toBeEnabled();
  await page.locator('#revert-last-good').click();

  await expect(page.getByTestId('mock-editor')).toHaveValue('s("bd*4")');
  await expect(page.locator('#revert-last-good')).toBeDisabled();
});

test('snapshot list can revert to an earlier snapshot', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('mock-editor').fill('s("first")');
  await page.getByRole('button', { name: 'Evaluate' }).click();
  await expect(page.locator('#status')).toContainText('Playing');

  await page.getByTestId('mock-editor').fill('s("second")');
  await page.getByRole('button', { name: 'Evaluate' }).click();
  await expect(page.locator('#status')).toContainText('Playing');

  await page.locator('.snapshot-item').filter({ hasText: 's("first")' }).getByRole('button', { name: 'Revert' }).click();

  await expect(page.getByTestId('mock-editor')).toHaveValue('s("first")');
  await expect(page.locator('#status')).toContainText('Reverted to snapshot');
});

test('panic calls stop and reports panic status', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Panic' }).click();

  await expect(page.locator('#status')).toContainText('Panic stop complete');
  await expect.poll(() => page.evaluate(() => window.__mockStopCalls)).toBe(1);
});

test('manual agent change stages diff without evaluating and can be undone', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('mock-editor')).not.toHaveValue('');
  const before = await page.getByTestId('mock-editor').inputValue();
  await page.locator('#agent-intent').fill('make the drums tighter');
  await page.getByRole('button', { name: 'Stage change' }).click();

  await expect(page.getByTestId('mock-editor')).toHaveValue(/Agent draft: make the drums tighter/);
  await expect(page.locator('#agent-diff')).toContainText('+ // Agent draft');
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(0);

  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(page.getByTestId('mock-editor')).toHaveValue(before);
});

test('auto fire evaluates a valid staged agent change', async ({ page }) => {
  await page.goto('/');
  await page.locator('#auto-fire').check();
  await page.locator('#agent-intent').fill('lift the energy');
  await page.getByRole('button', { name: 'Stage change' }).click();

  await expect(page.locator('#status')).toContainText('staged and playing');
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(1);
});

test('agent automatically reconciles edits made while a change is generating', async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  await page.route('**/changes', async (route) => {
    requests.push(JSON.parse(route.request().postData() ?? '{}') as Record<string, unknown>);
    if (requests.length === 1) await new Promise((resolve) => setTimeout(resolve, 150));
    await route.continue();
  });

  await page.goto('/');
  await page.locator('#auto-fire').check();
  await page.locator('#agent-intent').fill('make the drums tighter');
  await page.getByRole('button', { name: 'Stage change' }).click();
  await page.getByTestId('mock-editor').fill('s("user hats")');

  await expect(page.locator('#status')).toContainText('reconciling');
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toMatchObject({
    currentCode: 's("user hats")',
    reconciliation: {
      baseCode: expect.any(String),
      previousAgentCode: expect.stringContaining('Agent draft: make the drums tighter'),
      userEditDiff: expect.stringContaining('user hats'),
      attempt: 1,
    },
  });
  await expect(page.getByTestId('mock-editor')).toHaveValue(/s\("user hats"\)[\s\S]*Agent draft: make the drums tighter/);
  await expect(page.locator('#status')).toContainText('reconciled your latest edit');
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(0);
});

test('an in-flight agent request can be cancelled without changing the editor', async ({ page }) => {
  await page.route('**/changes', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2_000));
    await route.abort();
  });
  await page.goto('/');
  await expect(page.getByTestId('mock-editor')).not.toHaveValue('');
  const before = await page.getByTestId('mock-editor').inputValue();

  await page.locator('#agent-intent').fill('make a long transition');
  await page.getByRole('button', { name: 'Stage change' }).click();
  await expect(page.getByRole('button', { name: 'Stage change' })).toBeDisabled();
  await page.getByRole('button', { name: 'Cancel' }).click();

  await expect(page.locator('#status')).toContainText('cancelled');
  await expect(page.getByTestId('mock-editor')).toHaveValue(before);
  await expect(page.getByRole('button', { name: 'Stage change' })).toBeEnabled();
});

test('agent settings use backend defaults and persist browser overrides', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#agent-provider-summary')).toHaveText('mock');

  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.locator('#settings-dialog')).toBeVisible();
  await expect(page.locator('#settings-provider')).toContainText('Backend default (mock)');
  await expect(page.locator('#settings-provider')).toContainText('DeepSeek');
  await page.locator('#settings-provider').selectOption('openai');
  await expect(page.locator('#settings-api-key')).toBeEnabled();
  await expect(page.locator('#settings-model')).toHaveAttribute('placeholder', 'Default: gpt-5.6-terra');
  await page.locator('#settings-provider').selectOption('');
  await page.getByRole('button', { name: 'Test connection' }).click();
  await expect(page.locator('#settings-message')).toContainText('ready');

  await page.locator('#settings-model').fill('local-test-model');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.locator('#settings-dialog')).not.toBeVisible();
  await expect(page.locator('#agent-provider-summary')).toHaveText('mock / local-test-model');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('strudel-agent.settings.v1'))).toContain('local-test-model');
});

declare global {
  interface Window {
    __mockEvaluateCalls: number;
    __mockStopCalls: number;
    __mockEvaluateError: string | null;
  }
}
