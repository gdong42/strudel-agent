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

declare global {
  interface Window {
    __mockEvaluateCalls: number;
    __mockStopCalls: number;
    __mockEvaluateError: string | null;
  }
}
