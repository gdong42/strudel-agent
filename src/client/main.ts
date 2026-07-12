import {
  connectTrackEvents,
  createChange,
  createSnapshot,
  fetchSnapshots,
  fetchState,
  fetchTrack,
  revertSnapshot,
  saveTrack,
  undoChange,
  type SnapshotRecord,
  type TrackPayload,
} from './bridge';
import { AgentPanel } from './agent';
import { DiffView } from './diff';
import { preflightCode } from './preflight';
import { RecoveryView } from './recovery';
import { createReplAdapter, type ReplAdapter } from './repl';
import { SnapshotListView } from './snapshots';
import { SettingsPanel } from './settings';
import { RuntimeStateStore } from './state';
import { StatusView } from './status';
import './styles.css';

let repl: ReplAdapter | null = null;
let state: RuntimeStateStore | null = null;
let applyingRemoteCode = false;
let snapshotsCache: SnapshotRecord[] = [];

const replElement = requireElement<HTMLElement>('#repl');
const evaluateButton = requireElement<HTMLButtonElement>('#evaluate');
const revertButton = requireElement<HTMLButtonElement>('#revert-last-good');
const stopButton = requireElement<HTMLButtonElement>('#stop');
const panicButton = requireElement<HTMLButtonElement>('#panic');
const statusElement = requireElement<HTMLElement>('#status');
const snapshotListElement = requireElement<HTMLElement>('#snapshot-list');
const agentPanel = new AgentPanel(
  requireElement<HTMLFormElement>('#agent-form'),
  requireElement<HTMLTextAreaElement>('#agent-intent'),
  requireElement<HTMLInputElement>('#auto-fire'),
  requireElement<HTMLButtonElement>('#stage-change'),
  requireElement<HTMLButtonElement>('#undo-change'),
  requireElement<HTMLElement>('#agent-explanation'),
  requireElement<HTMLElement>('#agent-warnings'),
);
const settingsPanel = new SettingsPanel(
  requireElement<HTMLDialogElement>('#settings-dialog'),
  requireElement<HTMLButtonElement>('#open-settings'),
  requireElement<HTMLButtonElement>('#close-settings'),
  requireElement<HTMLFormElement>('#settings-form'),
  requireElement<HTMLSelectElement>('#settings-provider'),
  requireElement<HTMLInputElement>('#settings-model'),
  requireElement<HTMLInputElement>('#settings-api-key'),
  requireElement<HTMLInputElement>('#settings-remember-key'),
  requireElement<HTMLButtonElement>('#test-provider'),
  requireElement<HTMLButtonElement>('#clear-api-key'),
  requireElement<HTMLElement>('#settings-message'),
  requireElement<HTMLElement>('#agent-provider-summary'),
);
const diffView = new DiffView(requireElement<HTMLElement>('#agent-diff'));

function requireElement<TElement extends HTMLElement>(selector: string): TElement {
  const element = document.querySelector<TElement>(selector);
  if (!element) {
    throw new Error(`Missing required element: ${selector}`);
  }
  return element;
}

const status = new StatusView(statusElement);
const recovery = new RecoveryView(revertButton);
const snapshotList = new SnapshotListView(snapshotListElement);

function applyTrack(payload: TrackPayload): void {
  if (!repl) {
    status.set('Loaded. Waiting for REPL.', 'warn');
    return;
  }

  const currentCode = repl.getCode();
  const changed = payload.code !== currentCode;
  if (repl.isDirty() && changed) {
    status.set('Remote track update ignored because the editor has unsaved changes.', 'warn');
    return;
  }

  try {
    applyingRemoteCode = true;
    if (changed) {
      repl.setCode(payload.code);
    }
    repl.markClean();
    state?.loadTrack(payload);
    if (changed) {
      status.set('Loaded. Ready to evaluate.', 'ok');
    }
  } catch (error) {
    status.set(error instanceof Error ? error.message : String(error), 'error');
  } finally {
    applyingRemoteCode = false;
  }
}

async function evaluate(): Promise<void> {
  if (!repl || !state) {
    return;
  }

  const code = repl.getCode();
  state.setEditorCode(code);
  const preflight = preflightCode(code);

  if (preflight.errors.length > 0) {
    status.set(preflight.errors.join(' '), 'error');
    return;
  }

  try {
    await repl.evaluate();
    await saveTrack(code);
    const snapshot = await createSnapshot(code);
    snapshotsCache = [snapshot, ...snapshotsCache.filter((item) => item.id !== snapshot.id)];
    renderSnapshots();
    repl.markClean();
    state.markEvaluated(code, snapshot);

    const warning = preflight.warnings[0];
    status.set(warning ? `Playing with warning: ${warning}` : `Playing ${new Date().toLocaleTimeString()}`, warning ? 'warn' : 'ok');
  } catch (error) {
    status.set(error instanceof Error ? error.message : String(error), 'error');
  }
}

async function stageAgentChange(value: { intent: string; applyMode: 'manual' | 'auto' }): Promise<void> {
  if (!repl || !state) return;
  agentPanel.setBusy(true);
  try {
    const currentCode = repl.getCode();
    const change = await createChange({ ...value, currentCode }, settingsPanel.getConnection());
    applyingRemoteCode = true;
    repl.setCode(change.code);
    applyingRemoteCode = false;
    state.stageChange(change);
    agentPanel.showChange(change);
    diffView.render(change.preAgentCode, change.code);

    const hasRisk = change.warnings.some((warning) => warning.level === 'risk');
    const preflight = preflightCode(change.code);
    if (value.applyMode === 'auto' && !hasRisk && preflight.errors.length === 0) {
      await evaluate();
      status.set('Agent change staged and playing.', 'ok');
    } else if (value.applyMode === 'auto') {
      status.set('Agent change staged. Auto Fire blocked by validation warnings.', 'warn');
    } else {
      status.set('Agent change staged. Review it, then Evaluate when ready.', 'warn');
    }
  } catch (error) {
    applyingRemoteCode = false;
    status.set(error instanceof Error ? error.message : String(error), 'error');
  } finally {
    agentPanel.setBusy(false);
  }
}

async function undoAgentStage(): Promise<void> {
  if (!repl || !state?.get().changeSet) return;
  try {
    const result = await undoChange(state.get().changeSet!.id);
    applyingRemoteCode = true;
    repl.setCode(result.code);
    applyingRemoteCode = false;
    state.undoAgentChange(result.code);
    agentPanel.clearChange();
    diffView.clear();
    status.set('Agent change undone. Running music was not changed.', 'ok');
  } catch (error) {
    applyingRemoteCode = false;
    status.set(error instanceof Error ? error.message : String(error), 'error');
  }
}

async function revertToLastGood(): Promise<void> {
  if (!repl || !state || !state.canRevert()) {
    return;
  }

  const snapshotId = state.get().lastSnapshotId;

  try {
    if (snapshotId) {
      await revertToSnapshot(snapshotId);
      return;
    }

    const code = state.get().lastGoodCode;
    await saveTrack(code);
    state.markEvaluated(code, null);

    applyingRemoteCode = true;
    repl.setCode(code);
    repl.markClean();
    applyingRemoteCode = false;

    await repl.evaluate();
    status.set('Reverted to last successful evaluation.', 'ok');
  } catch (error) {
    applyingRemoteCode = false;
    status.set(error instanceof Error ? error.message : String(error), 'error');
  }
}

async function revertToSnapshot(snapshotId: string): Promise<void> {
  if (!repl || !state) {
    return;
  }

  try {
    const reverted = await revertSnapshot(snapshotId);
    const code = reverted.snapshot.code;
    state.markReverted(reverted.snapshot);

    applyingRemoteCode = true;
    repl.setCode(code);
    repl.markClean();
    applyingRemoteCode = false;

    await repl.evaluate();
    status.set('Reverted to snapshot.', 'ok');
  } catch (error) {
    applyingRemoteCode = false;
    status.set(error instanceof Error ? error.message : String(error), 'error');
  }
}

function renderSnapshots(): void {
  snapshotList.render(snapshotsCache, (snapshotId) => {
    revertToSnapshot(snapshotId);
  });
}

async function stop(): Promise<void> {
  await repl?.stop();
  agentPanel.disableAutoFire();
  status.set('Stopped', 'warn');
}

async function panic(): Promise<void> {
  await stop();
  status.set('Panic stop complete. Reload the page if visuals are stuck.', 'error');
}

async function boot(): Promise<void> {
  status.set('Waiting for REPL...', 'warn');

  const settingsReady = settingsPanel.initialize().catch(() => {
    status.set('Agent settings unavailable. REPL controls remain available.', 'warn');
  });
  const [serverState, snapshots] = await Promise.all([
    fetchState(),
    fetchSnapshots(),
    settingsReady,
  ]);
  state = new RuntimeStateStore(serverState);
  snapshotsCache = snapshots.snapshots;
  renderSnapshots();
  const latestSnapshot = snapshots.snapshots[0];
  if (latestSnapshot) {
    state.setLatestSnapshot(latestSnapshot);
  }
  state.subscribe((current) => {
    recovery.setCanRevert(current.editorCode !== current.lastGoodCode);
  });

  repl = await createReplAdapter(replElement);
  repl.onUpdate((code) => {
    if (!applyingRemoteCode) {
      state?.setEditorCode(code);
      if (repl?.isDirty()) {
        status.set('Editor changed. Evaluate to save and play.', 'warn');
      }
    }
  });

  const track = await fetchTrack();
  applyTrack(track);

  connectTrackEvents(
    (payload) => {
      applyTrack(payload);
    },
    () => {
      status.set('Event stream disconnected.', 'error');
    },
  );
}

evaluateButton.addEventListener('click', () => {
  evaluate();
});

recovery.onRevert(() => {
  revertToLastGood();
});

stopButton.addEventListener('click', () => {
  stop();
});

panicButton.addEventListener('click', () => {
  panic();
});

agentPanel.onSubmit((value) => { stageAgentChange(value); });
agentPanel.onUndo(() => { undoAgentStage(); });

boot().catch((error) => {
  status.set(error instanceof Error ? error.message : String(error), 'error');
});
