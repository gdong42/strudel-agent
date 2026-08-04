import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  acknowledgeAgentRunStage,
  answerAgentRun,
  cancelAgentRun,
  connectTrackEvents,
  fetchAgentRun,
  fetchSamples,
  resetAgentConversation,
  startAgentRun,
  updateAgentRunEditor,
  type AgentRunPublic,
} from '../../src/client/bridge';

const runningRun: AgentRunPublic = {
  id: 'run-1',
  status: 'running',
  question: null,
  finalChange: null,
  error: null,
  activities: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Agent Run bridge', () => {
  it('starts a run with the current editor version and transient provider headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(runningRun, 202));
    vi.stubGlobal('fetch', fetchMock);

    await expect(startAgentRun(
      {
        intent: 'make the drums tighter',
        editorVersion: { code: 's("bd*4")', hash: 'base-hash' },
        applyMode: 'manual',
        runtimeLimits: {
          maxTurns: 8,
          maxElapsedSeconds: 900,
          maxTotalTokens: null,
          maxOutputTokensPerTurn: 65_536,
        },
      },
      { provider: 'deepseek', model: 'deepseek-v4-pro', apiKey: 'browser-key' },
    )).resolves.toEqual(runningRun);

    expect(fetchMock).toHaveBeenCalledWith('/agent/runs', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Agent-Provider': 'deepseek',
        'X-Agent-Model': 'deepseek-v4-pro',
        'X-Agent-Api-Key': 'browser-key',
      },
      body: JSON.stringify({
        intent: 'make the drums tighter',
        editorVersion: { code: 's("bd*4")', hash: 'base-hash' },
        applyMode: 'manual',
        runtimeLimits: {
          maxTurns: 8,
          maxElapsedSeconds: 900,
          maxTotalTokens: null,
          maxOutputTokensPerTurn: 65_536,
        },
      }),
    });
  });

  it('reads and cancels an existing run', async () => {
    const cancelledRun: AgentRunPublic = { ...runningRun, status: 'cancelled' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(runningRun))
      .mockResolvedValueOnce(jsonResponse(cancelledRun));
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchAgentRun('run / 1')).resolves.toEqual(runningRun);
    await expect(cancelAgentRun('run / 1')).resolves.toEqual(cancelledRun);

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/agent/runs/run%20%2F%201');
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/agent/runs/run%20%2F%201/cancel', { method: 'POST' });
  });

  it('loads the declared sample catalog without credentials', async () => {
    const catalog = {
      configured: true,
      samples: [{ name: 'house_kick', tags: ['drum', 'kick'], description: 'Dry kick.' }],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(catalog));
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchSamples()).resolves.toEqual(catalog);

    expect(fetchMock).toHaveBeenCalledWith('/samples');
  });

  it('resets backend conversation context', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(resetAgentConversation()).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith('/agent/conversation', { method: 'DELETE' });
  });

  it('answers a paused run with transient provider headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(runningRun, 202));
    vi.stubGlobal('fetch', fetchMock);

    await expect(answerAgentRun(
      'run / 1',
      { questionId: 'tempo', answer: 'Keep it at 124 BPM.' },
      { provider: 'deepseek', model: 'deepseek-v4-pro', apiKey: 'browser-key' },
    )).resolves.toEqual(runningRun);

    expect(fetchMock).toHaveBeenCalledWith('/agent/runs/run%20%2F%201/input', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Agent-Provider': 'deepseek',
        'X-Agent-Model': 'deepseek-v4-pro',
        'X-Agent-Api-Key': 'browser-key',
      },
      body: JSON.stringify({ questionId: 'tempo', answer: 'Keep it at 124 BPM.' }),
    });
  });

  it('acknowledges a staged final with both editor hashes', async () => {
    const stagedChange = {
      id: 'change-1', projectId: 'local-project', sessionId: 'local-session', createdAt: 1,
      intent: 'make the drums tighter', applyMode: 'manual',
      preAgentCode: 's("bd")', code: 's("bd*4")', explanation: 'Added a kick.',
      action: 'apply' as const, provider: 'mock', model: null, latencyMs: 1, warnings: [], undoneAt: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stagedChange, 201));
    vi.stubGlobal('fetch', fetchMock);

    await expect(acknowledgeAgentRunStage('run / 1', {
      baseHash: 'base-hash',
      editorVersion: { code: 's("bd*4")', hash: 'final-hash' },
    })).resolves.toEqual(stagedChange);

    expect(fetchMock).toHaveBeenCalledWith('/agent/runs/run%20%2F%201/stage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        baseHash: 'base-hash',
        editorVersion: { code: 's("bd*4")', hash: 'final-hash' },
      }),
    });
  });

  it('sends an editor update from the last accepted hash', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(runningRun));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updateAgentRunEditor('run / 1', {
      baseHash: 'accepted-hash',
      editorVersion: { code: 's("hh*8")', hash: 'latest-hash' },
    })).resolves.toEqual(runningRun);

    expect(fetchMock).toHaveBeenCalledWith('/agent/runs/run%20%2F%201/editor', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        baseHash: 'accepted-hash',
        editorVersion: { code: 's("hh*8")', hash: 'latest-hash' },
      }),
    });
  });

  it('forwards public Agent Run events without affecting track events', () => {
    vi.stubGlobal('EventSource', FakeEventSource);
    const tracks: string[] = [];
    const runs: AgentRunPublic[] = [];
    const errors: string[] = [];
    const opens: string[] = [];

    connectTrackEvents(
      (track) => tracks.push(track.code),
      () => errors.push('error'),
      (run) => runs.push(run),
      () => opens.push('open'),
    );

    FakeEventSource.current?.emit('track', JSON.stringify({ projectId: 'p', sessionId: 's', code: 's("bd")', updatedAt: 1 }));
    FakeEventSource.current?.emit('agent-run', JSON.stringify(runningRun));
    FakeEventSource.current?.emit('error', '');
    FakeEventSource.current?.emit('open', '');

    expect(tracks).toEqual(['s("bd")']);
    expect(runs).toEqual([runningRun]);
    expect(errors).toEqual(['error']);
    expect(opens).toEqual(['open']);
  });
});

class FakeEventSource {
  static current: FakeEventSource | null = null;
  private readonly listeners = new Map<string, EventListener[]>();

  constructor(readonly url: string) {
    FakeEventSource.current = this;
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    if (typeof listener !== 'function') return;
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  emit(type: string, data: string): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data } as MessageEvent);
    }
  }
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
