import { describe, expect, it } from 'vitest';
import {
  loadBrowserAgentSettings,
  resolveAgentModelDefault,
  resolveAgentRuntimeLimits,
  saveBrowserAgentSettings,
} from '../../src/client/settings';

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
      {
        provider: 'openai', model: 'test-model', apiKey: 'secret', rememberApiKey: false,
        runtimeProfiles: {},
      },
      local,
      session,
    );

    expect(JSON.stringify(storageValues(local))).not.toContain('secret');
    expect(loadBrowserAgentSettings(local, session)).toEqual({
      provider: 'openai', model: 'test-model', apiKey: 'secret', rememberApiKey: false,
      runtimeProfiles: {},
    });
  });

  it('moves a remembered API key to persistent browser storage', () => {
    const local = new MemoryStorage();
    const session = new MemoryStorage();

    saveBrowserAgentSettings(
      {
        provider: 'openai', model: null, apiKey: 'persistent-secret', rememberApiKey: true,
        runtimeProfiles: {},
      },
      local,
      session,
    );

    expect(JSON.stringify(storageValues(session))).not.toContain('persistent-secret');
    expect(loadBrowserAgentSettings(local, session).apiKey).toBe('persistent-secret');
  });

  it('uses the project model when the selected provider matches the backend default', () => {
    const runtime = defaultRuntime();
    const backend = {
      defaultProvider: 'deepseek',
      defaultModel: 'deepseek-v4-flash',
      defaultRuntime: runtime,
      providers: [
        {
          id: 'deepseek', label: 'DeepSeek', requiresApiKey: true,
          defaultModel: 'deepseek-v4-pro', defaultRuntime: runtime,
        },
        {
          id: 'openai', label: 'OpenAI', requiresApiKey: true,
          defaultModel: 'gpt-5.6-terra', defaultRuntime: runtime,
        },
      ],
    };

    expect(resolveAgentModelDefault(backend, 'deepseek')).toBe('deepseek-v4-flash');
    expect(resolveAgentModelDefault(backend, 'openai')).toBe('gpt-5.6-terra');
  });

  it('resolves runtime overrides independently for each provider and model', () => {
    const runtime = defaultRuntime();
    const backend = {
      defaultProvider: 'deepseek',
      defaultModel: 'deepseek-v4-flash',
      defaultRuntime: runtime,
      providers: [
        {
          id: 'deepseek', label: 'DeepSeek', requiresApiKey: true,
          defaultModel: 'deepseek-v4-flash', defaultRuntime: runtime,
        },
      ],
    };
    const unlimited = { ...runtime, maxTotalTokens: null };
    const profiles = { '["deepseek","deepseek-v4-flash"]': unlimited };

    expect(resolveAgentRuntimeLimits(backend, profiles, 'deepseek', null)).toEqual(unlimited);
    expect(resolveAgentRuntimeLimits(backend, profiles, 'deepseek', 'another-model')).toEqual(runtime);
  });
});

function defaultRuntime() {
  return {
    maxTurns: 8,
    maxElapsedSeconds: 900,
    maxTotalTokens: 4_000_000,
    maxOutputTokensPerTurn: 65_536,
  };
}

function storageValues(storage: Storage): Array<string | null> {
  return Array.from({ length: storage.length }, (_, index) => storage.getItem(storage.key(index) ?? ''));
}
