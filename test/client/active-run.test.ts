import { describe, expect, it } from 'vitest';
import {
  ACTIVE_AGENT_RUN_KEY,
  clearActiveAgentRun,
  loadActiveAgentRun,
  saveActiveAgentRun,
} from '../../src/client/active-run';

describe('active Agent Run session storage', () => {
  it('round-trips public Run metadata without credentials', () => {
    const storage = new MemoryStorage();
    const run = {
      id: 'run-1',
      intent: 'make the drums tighter',
      editorVersion: { code: 's("bd")', hash: 'editor-hash' },
      applyMode: 'manual' as const,
      autoFireArmed: false,
    };

    saveActiveAgentRun(run, storage);

    expect(loadActiveAgentRun(storage)).toEqual(run);
    expect(storage.getItem(ACTIVE_AGENT_RUN_KEY)).not.toContain('apiKey');

    clearActiveAgentRun(storage);
    expect(loadActiveAgentRun(storage)).toBeNull();
  });

  it('ignores invalid stored values', () => {
    const storage = new MemoryStorage();
    storage.setItem(ACTIVE_AGENT_RUN_KEY, JSON.stringify({ id: 'run-1', applyMode: 'unsafe' }));

    expect(loadActiveAgentRun(storage)).toBeNull();
  });
});

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number { return this.values.size; }
  clear(): void { this.values.clear(); }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string): void { this.values.delete(key); }
  setItem(key: string, value: string): void { this.values.set(key, value); }
}
