import { describe, expect, it } from 'vitest';
import type { RuntimeStatePayload, SnapshotRecord, TrackPayload } from '../../src/client/bridge';
import { RuntimeStateStore } from '../../src/client/state';

const initialState: RuntimeStatePayload = {
  projectId: 'local-project',
  sessionId: 'local-session',
  activeCode: 's("bd")',
  editorCode: 's("bd")',
  lastGoodCode: 's("bd")',
};

function snapshot(code = 's("hh")'): SnapshotRecord {
  return {
    id: 'snapshot-1',
    projectId: 'local-project',
    sessionId: 'local-session',
    createdAt: 123,
    label: 'Manual evaluate',
    code,
  };
}

describe('RuntimeStateStore', () => {
  it('initializes from server state', () => {
    const store = new RuntimeStateStore(initialState);

    expect(store.get()).toEqual({
      ...initialState,
      lastSnapshotId: null,
      preAgentCode: null,
      changeSet: null,
    });
  });

  it('reports revert availability when editor differs from last good code', () => {
    const store = new RuntimeStateStore(initialState);

    expect(store.canRevert()).toBe(false);
    store.setEditorCode('s("hh")');

    expect(store.canRevert()).toBe(true);
  });

  it('marks successful evaluation as active and last good', () => {
    const store = new RuntimeStateStore(initialState);

    store.markEvaluated('s("cp")', snapshot('s("cp")'));

    expect(store.get().activeCode).toBe('s("cp")');
    expect(store.get().editorCode).toBe('s("cp")');
    expect(store.get().lastGoodCode).toBe('s("cp")');
    expect(store.get().lastSnapshotId).toBe('snapshot-1');
    expect(store.canRevert()).toBe(false);
  });

  it('loads track updates from SSE payloads', () => {
    const store = new RuntimeStateStore(initialState);
    const payload: TrackPayload = {
      projectId: 'local-project',
      sessionId: 'local-session',
      code: 's("bd hh")',
      updatedAt: 456,
    };

    store.loadTrack(payload);

    expect(store.get().editorCode).toBe('s("bd hh")');
  });

  it('notifies subscribers and supports unsubscribe', () => {
    const store = new RuntimeStateStore(initialState);
    const seen: string[] = [];

    const unsubscribe = store.subscribe((state) => seen.push(state.editorCode));
    store.setEditorCode('s("hh")');
    unsubscribe();
    store.setEditorCode('s("cp")');

    expect(seen).toEqual(['s("bd")', 's("hh")']);
  });

  it('marks reverted snapshot as active, editor, and last good code', () => {
    const store = new RuntimeStateStore(initialState);

    store.setEditorCode('s("broken")');
    store.markReverted(snapshot('s("bd*4")'));

    expect(store.get().activeCode).toBe('s("bd*4")');
    expect(store.get().editorCode).toBe('s("bd*4")');
    expect(store.get().lastGoodCode).toBe('s("bd*4")');
    expect(store.get().lastSnapshotId).toBe('snapshot-1');
    expect(store.canRevert()).toBe(false);
  });
});

it('stages and undoes an agent change without changing active code', () => {
  const store = new RuntimeStateStore(initialState);
  store.stageChange({
    id: 'change-1', projectId: 'p', sessionId: 's', createdAt: 1,
    intent: 'more groove', applyMode: 'manual',
    preAgentCode: 'old', code: 'new', explanation: 'changed groove', warnings: [], undoneAt: null,
  });

  expect(store.get().activeCode).toBe(initialState.activeCode);
  expect(store.get().editorCode).toBe('new');
  expect(store.get().preAgentCode).toBe('old');

  store.undoAgentChange('old');
  expect(store.get().editorCode).toBe('old');
  expect(store.get().changeSet).toBeNull();
});
