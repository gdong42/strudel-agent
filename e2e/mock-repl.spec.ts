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
  await page.getByTestId('mock-editor').fill('s("bd*4")');
  await page.getByRole('button', { name: 'Evaluate' }).click();

  await expect(page.locator('#status')).toContainText('Playing');
  await expect.poll(() => trackRequests.length).toBe(1);
  await expect.poll(() => snapshotRequests.length).toBe(1);
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(1);
});

test('desktop workspace uses a golden-ratio split', async ({ page }) => {
  await page.goto('/');

  const widths = await page.locator('main').evaluate((main) => {
    const editor = main.querySelector('#repl-host');
    const panel = main.querySelector('.side-panel');
    return {
      editor: editor?.getBoundingClientRect().width ?? 0,
      panel: panel?.getBoundingClientRect().width ?? 0,
    };
  });

  expect(widths.editor / widths.panel).toBeGreaterThan(1.6);
  expect(widths.editor / widths.panel).toBeLessThan(1.64);
  expect(widths.panel).toBeGreaterThanOrEqual(360);
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
  await expect(page.locator('#snapshots-dialog')).toBeHidden();
  const initialSnapshotCount = Number(await page.locator('#snapshot-count').textContent());
  await page.getByTestId('mock-editor').fill('s("first")');
  await page.getByRole('button', { name: 'Evaluate' }).click();
  await expect(page.locator('#status')).toContainText('Playing');

  await page.getByTestId('mock-editor').fill('s("second")');
  await page.getByRole('button', { name: 'Evaluate' }).click();
  await expect(page.locator('#status')).toContainText('Playing');
  await expect(page.locator('#snapshot-count')).toHaveText(String(initialSnapshotCount + 2));

  await page.locator('#open-snapshots').click();
  await expect(page.locator('#snapshots-dialog')).toBeVisible();

  const latestSnapshot = page.locator('.snapshot-item').first();
  await expect(latestSnapshot.locator('.snapshot-latest')).toHaveText('Latest');
  await expect(latestSnapshot.locator('.snapshot-additions')).toHaveText('+1');
  await expect(latestSnapshot.locator('.snapshot-removals')).toHaveText('-1');
  await expect(latestSnapshot.locator('.snapshot-preview')).toContainText('+ s("second")');
  await latestSnapshot.locator('.snapshot-diff-details summary').click();
  await expect(latestSnapshot.locator('.snapshot-diff-lines')).toContainText('+ s("second")');

  await page.locator('.snapshot-item').nth(1).getByRole('button', { name: 'Revert' }).click();

  await expect(page.locator('#snapshots-dialog')).toBeHidden();
  await expect(page.getByTestId('mock-editor')).toHaveValue('s("first")');
  await expect(page.locator('#status')).toContainText('Reverted to snapshot');
});

test('sample panel renders declared project sounds without treating them as playback state', async ({ page }) => {
  await page.route('**/samples', async (route) => {
    await route.fulfill({
      json: {
        configured: true,
        samples: [
          { name: 'house_kick', tags: ['drum', 'kick'], description: 'Dry kick.' },
          { name: 'house_hat', tags: ['drum', 'hat'], description: null },
        ],
        library: { configured: false, soundCount: 0, fileCount: 0, mapUrl: null },
      },
    });
  });

  await page.goto('/');

  await expect(page.locator('#sample-list')).toContainText('house_kick');
  await expect(page.locator('#sample-list')).toContainText('drum');
  await expect(page.locator('#sample-list')).toContainText('Dry kick.');
  await expect(page.locator('#sample-list')).not.toContainText('loaded');
});

test('workspace sample library map is registered during startup', async ({ page }) => {
  let mapRequests = 0;
  await page.route('**/samples', async (route) => {
    await route.fulfill({
      json: {
        configured: true,
        samples: [
          { name: 'kick', tags: [], description: '2 local sample files.' },
          { name: 'vocal', tags: [], description: '1 local sample file.' },
        ],
        library: {
          configured: true,
          soundCount: 2,
          fileCount: 3,
          mapUrl: '/sample-library/strudel.json?v=test',
        },
      },
    });
  });
  await page.route('**/sample-library/strudel.json?v=test', async (route) => {
    mapRequests += 1;
    await route.fulfill({
      json: {
        _base: '/sample-library/files/',
        kick: ['kick/deep.wav', 'kick/punch.wav'],
        vocal: ['vocal.wav'],
      },
    });
  });

  await page.goto('/');

  await expect(page.locator('#sample-list')).toContainText('2 local sounds · 3 files');
  await expect(page.locator('#sample-list')).toContainText('kick');
  await expect.poll(() => mapRequests).toBe(1);
});

test('panic calls stop and reports panic status', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Panic' }).click();

  await expect(page.locator('#status')).toContainText('Panic stop complete');
  await expect.poll(() => page.evaluate(() => window.__mockStopCalls)).toBe(1);
});

test('manual agent change stages diff without evaluating and can be undone', async ({ page }) => {
  const runRequests: Record<string, unknown>[] = [];
  const stageRequests: Record<string, unknown>[] = [];
  const deprecatedChangeGenerationRequests: string[] = [];
  await page.route('**/agent/runs**', async (route) => {
    if (/\/agent\/runs\/[^/]+\/stage$/.test(new URL(route.request().url()).pathname)) {
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    await route.continue();
  });
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/agent/runs')) {
      runRequests.push(JSON.parse(request.postData() ?? '{}') as Record<string, unknown>);
    }
    if (request.method() === 'POST' && /\/agent\/runs\/[^/]+\/stage$/.test(new URL(request.url()).pathname)) {
      stageRequests.push(JSON.parse(request.postData() ?? '{}') as Record<string, unknown>);
    }
    if (request.method() === 'POST' && request.url().endsWith('/changes')) {
      deprecatedChangeGenerationRequests.push(request.postData() ?? '');
    }
  });

  await page.goto('/');
  await expect(page.getByTestId('mock-editor')).not.toHaveValue('');
  const before = await page.getByTestId('mock-editor').inputValue();
  await page.locator('#agent-intent').fill('make the drums tighter');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.locator('#agent-intent')).toHaveValue('');
  await expect(page.locator('#agent-user-message')).toHaveText('make the drums tighter');
  await expect(page.getByTestId('mock-editor')).toHaveValue(/Agent draft: make the drums tighter/);
  await expect(page.locator('#agent-diff')).toContainText('+ // Agent draft');
  await expect(page.getByRole('button', { name: 'Undo' })).toBeDisabled();
  await expect(page.locator('#status')).toContainText('staged. Review it');
  await expect(page.getByRole('button', { name: 'Undo' })).toBeEnabled();
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(0);
  await expect.poll(() => runRequests.length).toBe(1);
  await expect.poll(() => stageRequests.length).toBe(1);
  expect(runRequests[0]).toMatchObject({
    intent: 'make the drums tighter',
    applyMode: 'manual',
    editorVersion: { code: before, hash: expect.any(String) },
  });
  expect(stageRequests[0]).toMatchObject({
    baseHash: expect.any(String),
    editorVersion: { code: expect.stringContaining('Agent draft: make the drums tighter'), hash: expect.any(String) },
  });
  expect(deprecatedChangeGenerationRequests).toHaveLength(0);

  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(page.getByTestId('mock-editor')).toHaveValue(before);
});

test('agent composer stays below the transcript and preserves an instruction when startup fails', async ({ page }) => {
  await page.route('**/agent/runs', async (route) => {
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Provider unavailable.' }) });
  });

  await page.goto('/');
  expect(await page.locator('#agent-transcript').evaluate((transcript) => (
    Boolean(transcript.compareDocumentPosition(document.querySelector('#agent-form')) & Node.DOCUMENT_POSITION_FOLLOWING)
  ))).toBe(true);
  await page.locator('#agent-intent').fill('add brighter chords');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.locator('#status')).toContainText('Provider unavailable');
  await expect(page.locator('#agent-intent')).toHaveValue('add brighter chords');
  await expect(page.locator('#agent-user-message')).toBeHidden();
});

test('a new Agent turn archives the previous result and diff in the scrolling transcript', async ({ page }) => {
  await page.goto('/');
  await page.locator('#agent-intent').fill('tighten the drums');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.locator('#status')).toContainText('staged. Review it');
  await expect(page.locator('#agent-diff')).toContainText('Agent draft: tighten the drums');
  await expect(page.locator('#agent-activity')).not.toHaveAttribute('open', '');
  await expect(page.locator('#agent-activity-summary')).toHaveText('Worked for');
  await expect(page.locator('#agent-activity-elapsed')).toHaveText(/\d+(?:m \d+)?s/);
  expect(await page.locator('#agent-activity').evaluate((activity) => {
    const result = document.querySelector('#agent-result');
    return activity.getBoundingClientRect().bottom <= result.getBoundingClientRect().top;
  })).toBe(true);

  await page.locator('#agent-intent').fill('brighten the chords');
  await page.getByRole('button', { name: 'Send' }).click();

  const archivedTurn = page.locator('#agent-turn-history .agent-turn-archived');
  await expect(archivedTurn).toHaveCount(1);
  await expect(archivedTurn).toContainText('tighten the drums');
  await expect(archivedTurn).toContainText('Agent draft: tighten the drums');
  await expect(page.locator('#agent-user-message')).toHaveText('brighten the chords');
  await expect(page.locator('#agent-diff')).toContainText('Agent draft: brighten the chords');
});

test('agent can create the first track from an empty editor', async ({ page }) => {
  const runRequests: Array<{ editorVersion: { code: string; hash: string } }> = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/agent/runs')) {
      runRequests.push(request.postDataJSON() as { editorVersion: { code: string; hash: string } });
    }
  });

  await page.goto('/');
  await page.getByTestId('mock-editor').fill('');
  await page.locator('#agent-intent').fill('start a minimal house beat');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.locator('#status')).toContainText('staged. Review it');
  await expect(page.getByTestId('mock-editor')).toHaveValue(/s\("bd\*4"\)/);
  await expect.poll(() => runRequests.length).toBe(1);
  expect(runRequests[0].editorVersion).toMatchObject({ code: '', hash: expect.any(String) });
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(0);
});

test('agent can answer without changing or staging editor code', async ({ page }) => {
  let stageRequests = 0;
  await page.route('**/agent/runs', async (route) => {
    await route.fulfill({
      status: 202,
      json: {
        id: 'response-run',
        status: 'completed',
        question: null,
        finalChange: null,
        finalResponse: {
          content: '## Current rhythm\n\nThe kick plays **four times** per cycle.',
        },
        error: null,
        activities: [{
          sequence: 1,
          kind: 'model_turn',
          status: 'completed',
          startedAt: 100,
          completedAt: 101,
          turn: 1,
          tool: null,
          message: null,
        }],
      },
    });
  });
  page.on('request', (request) => {
    if (/\/agent\/runs\/[^/]+\/stage$/.test(new URL(request.url()).pathname)) stageRequests += 1;
  });
  await page.goto('/');
  const before = await page.getByTestId('mock-editor').inputValue();

  await page.locator('#agent-intent').fill('Explain the current rhythm.');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.locator('#agent-explanation h2')).toHaveText('Current rhythm');
  await expect(page.locator('#agent-explanation strong')).toHaveText('four times');
  await expect(page.locator('#agent-activity-list')).toContainText('Working on request');
  await expect(page.locator('#agent-activity-list')).not.toContainText('Generating change');
  await expect(page.locator('#agent-diff')).toBeEmpty();
  await expect(page.getByTestId('mock-editor')).toHaveValue(before);
  await expect(page.locator('#status')).toContainText('response ready');
  await expect.poll(() => stageRequests).toBe(0);
});

test('Auto Fire evaluates only after the final Run stage is acknowledged', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#auto-fire')).toBeEnabled();
  await page.locator('#auto-fire').check();
  await page.locator('#agent-intent').fill('lift the energy');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.locator('#status')).toContainText('change is playing');
  await expect(page.locator('#agent-result')).toBeVisible();
  await expect(page.locator('#agent-diff')).toContainText('Agent draft: lift the energy');
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(1);
  await expect(page.getByRole('button', { name: 'Undo' })).toBeDisabled();
});

test('Auto Fire keeps a final with risk warnings staged for manual review', async ({ page }) => {
  const finalCode = 's("bd*4")';
  const completedRun = {
    id: 'risk-run',
    status: 'completed',
    question: null,
    finalChange: {
      code: finalCode,
      explanation: '**Added** a `bd` kick.\n\n- Four on the floor\n- Kept the bass unchanged\n\n[unsafe](javascript:alert(1))\n\n<img src=x onerror=alert(1)>',
      action: 'apply',
      warnings: [{ level: 'risk', message: 'Unverified sample.', category: 'sample' }],
    },
    error: null,
  };
  const stagedChange = {
    id: 'risk-change', projectId: 'local-project', sessionId: 'local-session', createdAt: 1,
    intent: 'add a risky kick', applyMode: 'auto', preAgentCode: 's("bd")', code: finalCode,
    explanation: completedRun.finalChange.explanation, action: 'apply', provider: 'mock', model: null,
    latencyMs: 1, warnings: completedRun.finalChange.warnings, undoneAt: null,
  };
  await page.route('**/agent/runs**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path === '/agent/runs') {
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(completedRun) });
      return;
    }
    if (request.method() === 'GET' && path === '/agent/runs/risk-run') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(completedRun) });
      return;
    }
    if (request.method() === 'POST' && path === '/agent/runs/risk-run/stage') {
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(stagedChange) });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await page.locator('#auto-fire').check();
  await page.locator('#agent-intent').fill('add a risky kick');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.getByTestId('mock-editor')).toHaveValue(finalCode);
  await expect(page.locator('#status')).toContainText('Auto Fire blocked by risk warnings');
  await expect(page.locator('#agent-explanation strong')).toHaveText('Added');
  await expect(page.locator('#agent-explanation code')).toHaveText('bd');
  await expect(page.locator('#agent-explanation li')).toHaveCount(2);
  await expect(page.locator('#agent-explanation a')).not.toHaveAttribute('href');
  await expect(page.locator('#agent-explanation img')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Undo' })).toBeEnabled();
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(0);
});

test('agent activity timeline shows live model progress and safe tool names', async ({ page }) => {
  const startedAt = Math.floor(Date.now() / 1000) - 3;
  const runningRun = {
    id: 'activity-run',
    status: 'running',
    question: null,
    finalChange: null,
    error: null,
    activities: [
      {
        sequence: 1,
        kind: 'model_turn',
        status: 'running',
        startedAt,
        completedAt: null,
        turn: 1,
        tool: null,
        message: null,
      },
    ],
  };
  const progressedRun = {
    ...runningRun,
    activities: [
      { ...runningRun.activities[0], status: 'completed', completedAt: startedAt + 1 },
      {
        sequence: 2,
        kind: 'commentary',
        status: 'completed',
        startedAt,
        completedAt: startedAt + 1,
        turn: null,
        tool: null,
        message: '**Balancing** the drums before `validation`.',
      },
      {
        sequence: 3,
        kind: 'tool',
        status: 'completed',
        startedAt: startedAt + 1,
        completedAt: startedAt + 1,
        turn: null,
        tool: 'inspect_diff',
        message: null,
      },
      {
        sequence: 4,
        kind: 'model_turn',
        status: 'running',
        startedAt: startedAt + 1,
        completedAt: null,
        turn: 2,
        tool: null,
        message: null,
      },
    ],
  };
  await page.route('**/agent/runs**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path === '/agent/runs') {
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(runningRun) });
      return;
    }
    if (request.method() === 'GET' && path === '/agent/runs/activity-run') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(progressedRun) });
      return;
    }
    if (request.method() === 'POST' && path === '/agent/runs/activity-run/cancel') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ...progressedRun, status: 'cancelled' }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await page.locator('#agent-intent').fill('make a long transition');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.locator('#agent-activity')).toBeVisible();
  await expect(page.locator('#agent-activity-summary')).toContainText('Working · Turn 2');
  await expect(page.locator('#agent-activity-list')).toContainText('Working on request');
  await expect(page.locator('#agent-activity-list')).toContainText('Balancing the drums before validation.');
  await expect(page.locator('#agent-activity-list strong')).toHaveText('Balancing');
  await expect(page.locator('#agent-activity-list .markdown-content code')).toHaveText('validation');
  await expect(page.locator('#agent-activity-list')).toContainText('Reviewing code changes');
  await expect(page.locator('#agent-activity-list')).toContainText('inspect_diff');
  await expect(page.locator('#agent-activity-list')).toContainText('Continuing request');
  await expect(page.locator('#agent-activity-list')).not.toContainText('candidateCode');
  await expect(page.locator('#agent-activity-list')).not.toContainText('PRIVATE reasoning');
  await expect(page.locator('#agent-activity')).toHaveAttribute('open', '');

  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.locator('#agent-activity-summary')).toHaveText('Cancelled after');
  await expect(page.locator('#agent-activity')).not.toHaveAttribute('open', '');
});

test('a running Agent Run recovers a missed terminal event by polling', async ({ page }) => {
  const startedAt = Math.floor(Date.now() / 1000);
  const runningRun = {
    id: 'poll-run',
    status: 'running',
    question: null,
    finalChange: null,
    error: null,
    activities: [{
      sequence: 1,
      kind: 'model_turn',
      status: 'running',
      startedAt,
      completedAt: null,
      turn: 1,
      tool: null,
      message: null,
    }],
  };
  const finalCode = 's("bd*4")';
  const completedRun = {
    ...runningRun,
    status: 'completed',
    finalChange: {
      code: finalCode,
      explanation: 'Added a four-on-the-floor kick.',
      action: 'apply',
      warnings: [],
    },
    activities: [{ ...runningRun.activities[0], status: 'completed', completedAt: startedAt + 1 }],
  };
  const stagedChange = {
    id: 'poll-change', projectId: 'local-project', sessionId: 'local-session', createdAt: 1,
    intent: 'add a steady kick', applyMode: 'manual', preAgentCode: 's("bd")', code: finalCode,
    explanation: completedRun.finalChange.explanation, action: 'apply', provider: 'mock', model: null,
    latencyMs: 1, warnings: [], undoneAt: null,
  };
  let runReads = 0;
  await page.route('**/agent/runs**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path === '/agent/runs') {
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(runningRun) });
      return;
    }
    if (request.method() === 'GET' && path === '/agent/runs/poll-run') {
      runReads += 1;
      const body = runReads === 1 ? runningRun : completedRun;
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
      return;
    }
    if (request.method() === 'POST' && path === '/agent/runs/poll-run/stage') {
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(stagedChange) });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await page.getByTestId('mock-editor').fill('s("bd")');
  await page.locator('#agent-intent').fill('add a steady kick');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.getByTestId('mock-editor')).toHaveValue(finalCode);
  await expect(page.locator('#status')).toContainText('staged. Review it');
  await expect.poll(() => runReads).toBeGreaterThanOrEqual(2);
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(0);
});

test('editor updates reach an active Agent Run in accepted-hash order', async ({ page }) => {
  const runningRun = { id: 'sync-run', status: 'running', question: null, finalChange: null, error: null };
  const editorUpdates: Array<{ baseHash: string; editorVersion: { code: string; hash: string } }> = [];
  await page.route('**/agent/runs**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path === '/agent/runs') {
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(runningRun) });
      return;
    }
    if (request.method() === 'GET' && path === '/agent/runs/sync-run') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(runningRun) });
      return;
    }
    if (request.method() === 'POST' && path === '/agent/runs/sync-run/editor') {
      editorUpdates.push(JSON.parse(request.postData() ?? '{}') as typeof editorUpdates[number]);
      if (editorUpdates.length === 1) {
        await new Promise((resolve) => setTimeout(resolve, 150));
      }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(runningRun) });
      return;
    }
    if (request.method() === 'POST' && path === '/agent/runs/sync-run/cancel') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...runningRun, status: 'cancelled' }) });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await page.locator('#agent-intent').fill('make a long transition');
  await page.getByRole('button', { name: 'Send' }).click();
  await page.getByTestId('mock-editor').fill('s("first edit")');
  await expect.poll(() => editorUpdates.length).toBe(1);
  await page.getByTestId('mock-editor').fill('s("second edit")');
  await expect.poll(() => editorUpdates.length).toBe(2);

  expect(editorUpdates[0].editorVersion.code).toBe('s("first edit")');
  expect(editorUpdates[1].baseHash).toBe(editorUpdates[0].editorVersion.hash);
  expect(editorUpdates[1].editorVersion.code).toBe('s("second edit")');

  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.locator('#status')).toContainText('cancelled');
});

test('a stale completed Agent Run reconciles against a concurrent editor edit', async ({ page }) => {
  let started = false;
  const editorUpdates: Record<string, unknown>[] = [];
  await page.route('**/agent/runs', async (route) => {
    if (route.request().method() === 'POST') {
      started = true;
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    await route.continue();
  });
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/agent\/runs\/[^/]+\/editor$/.test(new URL(request.url()).pathname)) {
      editorUpdates.push(JSON.parse(request.postData() ?? '{}') as Record<string, unknown>);
    }
  });

  await page.goto('/');
  await page.locator('#agent-intent').fill('make the drums tighter');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect.poll(() => started).toBe(true);
  await page.getByTestId('mock-editor').fill('s("user hats")');

  await expect(page.locator('#status')).toContainText('staged. Review it');
  await expect.poll(() => editorUpdates.length).toBe(1);
  expect(editorUpdates[0]).toMatchObject({
    editorVersion: { code: 's("user hats")', hash: expect.any(String) },
  });
  await expect(page.getByTestId('mock-editor')).toHaveValue(/s\("user hats"\)[\s\S]*Agent draft: make the drums tighter/);
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(0);
});

test('an active Agent Run can be cancelled without changing the editor', async ({ page }) => {
  const runningRun = { id: 'slow-run', status: 'running', question: null, finalChange: null, error: null };
  await page.route('**/agent/runs**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path === '/agent/runs') {
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(runningRun) });
      return;
    }
    if (request.method() === 'GET' && path === '/agent/runs/slow-run') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(runningRun) });
      return;
    }
    if (request.method() === 'POST' && path === '/agent/runs/slow-run/cancel') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ...runningRun, status: 'cancelled' }),
      });
      return;
    }
    await route.continue();
  });
  await page.goto('/');
  await expect(page.getByTestId('mock-editor')).not.toHaveValue('');
  const before = await page.getByTestId('mock-editor').inputValue();

  await page.locator('#agent-intent').fill('make a long transition');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
  await page.getByRole('button', { name: 'Cancel' }).click();

  await expect(page.locator('#status')).toContainText('cancelled');
  await expect(page.getByTestId('mock-editor')).toHaveValue(before);
  await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
});

test('a failed Agent Run leaves the editor and performance state unchanged', async ({ page }) => {
  const runningRun = { id: 'failed-run', status: 'running', question: null, finalChange: null, error: null };
  const failedRun = {
    ...runningRun,
    status: 'failed',
    error: { code: 'provider_error', message: 'The provider is unavailable.', retryable: true },
  };
  const stageRequests: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/stage')) {
      stageRequests.push(request.postData() ?? '');
    }
  });
  await page.route('**/agent/runs**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path === '/agent/runs') {
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(runningRun) });
      return;
    }
    if (request.method() === 'GET' && path === '/agent/runs/failed-run') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(failedRun) });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await expect(page.getByTestId('mock-editor')).not.toHaveValue('');
  const before = await page.getByTestId('mock-editor').inputValue();
  await page.locator('#agent-intent').fill('make the drums more intense');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.locator('#status')).toContainText('The provider is unavailable.');
  await expect(page.getByTestId('mock-editor')).toHaveValue(before);
  await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Cancel' })).toBeHidden();
  await expect(page.getByRole('button', { name: 'Undo' })).toBeDisabled();
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(0);
  expect(stageRequests).toHaveLength(0);
});

test('a paused Agent Run exposes only its clarification question and options', async ({ page }) => {
  const pausedRun = {
    id: 'clarify-run',
    status: 'needs_input',
    question: {
      id: 'tempo',
      question: 'Keep the current tempo?',
      options: [
        { id: 'keep', label: 'Keep it', description: 'Stay at 124 BPM.' },
        { id: 'raise', label: 'Raise it', description: 'Move toward 128 BPM.' },
      ],
      reason: 'private ambiguity analysis',
    },
    finalChange: null,
    error: null,
    internalCandidate: 's("bd*4").gain(1.5)',
  };
  await page.route('**/agent/runs**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path === '/agent/runs') {
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(pausedRun) });
      return;
    }
    if (request.method() === 'GET' && path === '/agent/runs/clarify-run') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(pausedRun) });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await expect(page.getByTestId('mock-editor')).not.toHaveValue('');
  const before = await page.getByTestId('mock-editor').inputValue();
  await page.locator('#agent-intent').fill('make the drums more energetic');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.locator('#agent-question')).toBeVisible();
  await expect(page.locator('#agent-user-message')).toHaveText('make the drums more energetic');
  await expect(page.locator('#agent-question-text')).toHaveText('Keep the current tempo?');
  await expect(page.locator('#agent-question-options')).toContainText('Keep it');
  await expect(page.locator('#agent-question-options')).toContainText('Stay at 124 BPM.');
  await expect(page.locator('#agent-question-options')).toContainText('Raise it');
  await expect(page.getByTestId('mock-editor')).toHaveValue(before);
  await expect(page.locator('body')).not.toContainText('private ambiguity analysis');
  await expect(page.locator('body')).not.toContainText('gain(1.5)');
});

test('a clarification answer resumes the same Run after syncing the latest editor version', async ({ page }) => {
  const pausedRun = {
    id: 'answer-run',
    status: 'needs_input',
    question: {
      id: 'tempo',
      question: 'Keep the current tempo?',
      options: [{ id: 'raise', label: 'Raise it', description: 'Move toward 128 BPM.' }],
    },
    finalChange: null,
    error: null,
    activities: [
      {
        sequence: 1,
        kind: 'model_turn',
        status: 'completed',
        startedAt: Math.floor(Date.now() / 1000) - 2,
        completedAt: Math.floor(Date.now() / 1000) - 1,
        turn: 1,
        tool: null,
        message: null,
      },
      {
        sequence: 2,
        kind: 'tool',
        status: 'completed',
        startedAt: Math.floor(Date.now() / 1000) - 1,
        completedAt: Math.floor(Date.now() / 1000) - 1,
        turn: null,
        tool: 'request_user_input',
        message: null,
      },
    ],
  };
  const runningRun = { ...pausedRun, status: 'running', question: null };
  const commands: string[] = [];
  const editorUpdates: Array<{ baseHash: string; editorVersion: { code: string; hash: string } }> = [];
  const answers: Array<{ questionId: string; answer: string }> = [];
  await page.route('**/agent/runs**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && path === '/agent/runs') {
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(pausedRun) });
      return;
    }
    if (request.method() === 'GET' && path === '/agent/runs/answer-run') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(pausedRun) });
      return;
    }
    if (request.method() === 'POST' && path === '/agent/runs/answer-run/editor') {
      commands.push('editor');
      editorUpdates.push(JSON.parse(request.postData() ?? '{}') as typeof editorUpdates[number]);
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(pausedRun) });
      return;
    }
    if (request.method() === 'POST' && path === '/agent/runs/answer-run/input') {
      commands.push('input');
      answers.push(JSON.parse(request.postData() ?? '{}') as typeof answers[number]);
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(runningRun) });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await expect(page.getByTestId('mock-editor')).not.toHaveValue('');
  await page.locator('#agent-intent').fill('make the drums more energetic');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.locator('#agent-question')).toBeVisible();

  await page.getByTestId('mock-editor').fill('s("user hats")');
  await page.getByLabel('Raise it').check();
  await expect(page.getByRole('button', { name: 'Continue' })).toBeEnabled();
  await page.getByRole('button', { name: 'Continue' }).click();

  await expect.poll(() => commands).toEqual(['editor', 'input']);
  expect(editorUpdates[0].editorVersion.code).toBe('s("user hats")');
  expect(answers).toEqual([{ questionId: 'tempo', answer: 'Raise it' }]);
  await expect(page.locator('#agent-question')).toBeHidden();
  await expect(page.locator('#status')).toContainText('Agent is working');
  await expect(page.getByTestId('mock-editor')).toHaveValue('s("user hats")');
  await expect.poll(() => page.evaluate(() => window.__mockEvaluateCalls)).toBe(0);
});

test('a browser reload restores a paused Agent Run without storing credentials', async ({ page }) => {
  const storedRun = {
    id: 'reload-run',
    intent: 'make the drums more energetic',
    editorVersion: { code: 's("bd")', hash: 'stored-editor-hash' },
    applyMode: 'manual',
    autoFireArmed: false,
  };
  const pausedRun = {
    id: 'reload-run',
    status: 'needs_input',
    question: {
      id: 'tempo',
      question: 'Keep the current tempo?',
      options: [{ id: 'keep', label: 'Keep it', description: 'Stay at 124 BPM.' }],
    },
    finalChange: null,
    error: null,
    activities: [
      {
        sequence: 1,
        kind: 'model_turn',
        status: 'completed',
        startedAt: Math.floor(Date.now() / 1000) - 2,
        completedAt: Math.floor(Date.now() / 1000) - 1,
        turn: 1,
        tool: null,
        message: null,
      },
      {
        sequence: 2,
        kind: 'tool',
        status: 'completed',
        startedAt: Math.floor(Date.now() / 1000) - 1,
        completedAt: Math.floor(Date.now() / 1000) - 1,
        turn: null,
        tool: 'request_user_input',
        message: null,
      },
    ],
  };
  let runReads = 0;
  await page.addInitScript((run) => {
    sessionStorage.setItem('strudel-agent.active-run.v1', JSON.stringify(run));
  }, storedRun);
  await page.route('**/agent/runs/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET' && path === '/agent/runs/reload-run') {
      runReads += 1;
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(pausedRun) });
      return;
    }
    if (request.method() === 'POST' && path === '/agent/runs/reload-run/cancel') {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ...pausedRun, status: 'cancelled', question: null }) });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await expect(page.locator('#agent-question')).toBeVisible();
  await expect(page.locator('#agent-user-message')).toHaveText(storedRun.intent);
  await page.reload();
  await expect(page.locator('#agent-question')).toBeVisible();
  await expect(page.locator('#agent-activity-list')).toContainText('Preparing a clarification');
  await expect(page.locator('#agent-activity-list')).toContainText('request_user_input');
  await expect.poll(() => runReads).toBeGreaterThanOrEqual(2);
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('strudel-agent.active-run.v1'))).not.toContain('apiKey');

  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.locator('#status')).toContainText('cancelled');
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('strudel-agent.active-run.v1'))).toBeNull();
});

test('agent settings use backend defaults and persist browser overrides', async ({ page }) => {
  let runRequest: Record<string, unknown> | null = null;
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/agent/runs')) {
      runRequest = request.postDataJSON() as Record<string, unknown>;
    }
  });
  await page.goto('/');
  await expect(page.locator('#agent-provider-summary')).toHaveText('mock');

  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.locator('#settings-dialog')).toBeVisible();
  await expect(page.locator('#settings-provider')).toContainText('Backend default (mock)');
  await expect(page.locator('#settings-provider')).toContainText('DeepSeek');
  await expect(page.locator('#settings-provider')).toContainText('Kimi');
  await expect(page.locator('.settings-legal')).toContainText('Copyright (C) 2026 Gan Dong');
  await expect(page.getByRole('link', { name: 'Source code' })).toHaveAttribute(
    'href',
    'https://github.com/gdong42/strudel-agent',
  );
  await expect(page.getByRole('link', { name: 'License' })).toHaveAttribute(
    'href',
    'https://github.com/gdong42/strudel-agent/blob/main/LICENSE',
  );
  await page.locator('#settings-provider').selectOption('openai');
  await expect(page.locator('#settings-api-key')).toBeEnabled();
  await expect(page.locator('#settings-model')).toHaveAttribute('placeholder', 'Default: gpt-5.6-terra');
  await page.locator('#settings-provider').selectOption('');
  await page.getByRole('button', { name: 'Test connection' }).click();
  await expect(page.locator('#settings-message')).toContainText('ready');

  await page.locator('#settings-model').fill('local-test-model');
  await page.locator('#settings-model').press('Tab');
  await page.locator('.settings-advanced summary').click();
  await expect(page.locator('#settings-max-turns')).toHaveValue('8');
  await expect(page.locator('#settings-max-elapsed')).toHaveValue('900');
  await expect(page.locator('#settings-max-total-tokens')).toHaveValue('4000000');
  await expect(page.locator('#settings-max-output-tokens')).toHaveValue('65536');
  await page.locator('#settings-unlimited-total-tokens').check();
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.locator('#settings-dialog')).not.toBeVisible();
  await expect(page.locator('#agent-provider-summary')).toHaveText('mock / local-test-model');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('strudel-agent.settings.v2'))).toContain('local-test-model');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('strudel-agent.settings.v2'))).toContain('"maxTotalTokens":null');

  await page.locator('#agent-intent').fill('Make it groovier.');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect.poll(() => runRequest).not.toBeNull();
  expect(runRequest?.runtimeLimits).toEqual({
    maxTurns: 8,
    maxElapsedSeconds: 900,
    maxTotalTokens: null,
    maxOutputTokensPerTurn: 65_536,
  });
});

test('reset context clears the visible conversation through the backend', async ({ page }) => {
  let resetRequests = 0;
  await page.route('**/agent/conversation', async (route) => {
    if (route.request().method() === 'DELETE') resetRequests += 1;
    await route.fulfill({ json: { ok: true } });
  });
  await page.goto('/');
  await page.locator('#agent-turn-history').evaluate((history) => {
    history.append(Object.assign(document.createElement('article'), { textContent: 'Earlier Agent result' }));
  });
  await expect(page.locator('#agent-turn-history')).toContainText('Earlier Agent result');

  await page.getByRole('button', { name: 'Reset context' }).click();

  await expect.poll(() => resetRequests).toBe(1);
  await expect(page.locator('#agent-turn-history')).toBeEmpty();
  await expect(page.locator('#status')).toContainText('conversation context reset');
});

declare global {
  interface Window {
    __mockEvaluateCalls: number;
    __mockStopCalls: number;
    __mockEvaluateError: string | null;
  }
}
