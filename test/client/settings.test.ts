import { describe, expect, it } from 'vitest';
import { loadBrowserAgentSettings, saveBrowserAgentSettings } from '../../src/client/settings';

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();
  get length(): number { return this.values.size; }
  clear(): void { this.values.clear(); }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string): void { this.values.delete(key); }
  setItem(key: string, value: string): void { this.values.set(key, value); }
}

describe('browser agent settings', () => {
  it('keeps a non-remembered API key in session storage', () => {
    const local = new MemoryStorage();
    const session = new MemoryStorage();

    saveBrowserAgentSettings(
      { provider: 'openai', model: 'test-model', apiKey: 'secret', rememberApiKey: false },
      local,
      session,
    );

    expect(JSON.stringify(storageValues(local))).not.toContain('secret');
    expect(loadBrowserAgentSettings(local, session)).toEqual({
      provider: 'openai', model: 'test-model', apiKey: 'secret', rememberApiKey: false,
    });
  });

  it('moves a remembered API key to persistent browser storage', () => {
    const local = new MemoryStorage();
    const session = new MemoryStorage();

    saveBrowserAgentSettings(
      { provider: 'openai', model: null, apiKey: 'persistent-secret', rememberApiKey: true },
      local,
      session,
    );

    expect(JSON.stringify(storageValues(session))).not.toContain('persistent-secret');
    expect(loadBrowserAgentSettings(local, session).apiKey).toBe('persistent-secret');
  });
});

function storageValues(storage: Storage): Array<string | null> {
  return Array.from({ length: storage.length }, (_, index) => storage.getItem(storage.key(index) ?? ''));
}
