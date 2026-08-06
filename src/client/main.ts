import '@fontsource-variable/ibm-plex-sans/wght.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import {
  acknowledgeAgentRunStage,
  answerAgentRun,
  cancelAgentRun,
  connectTrackEvents,
  createSnapshot,
  fetchAgentRun,
  fetchSamples,
  fetchSnapshots,
  fetchState,
  fetchTrack,
  revertSnapshot,
  resetAgentConversation,
  saveTrack,
  startAgentRun,
  undoChange,
  updateAgentRunEditor,
  type ApplyMode,
  type AgentRunPublic,
  type EditorVersion,
  type SnapshotRecord,
  type TrackPayload,
} from './bridge';
import {
  AudioWaveform,
  createIcons,
  History,
  OctagonAlert,
  Play,
  RefreshCcw,
  RotateCcw,
  Send,
  Settings,
  Square,
  Undo2,
  X,
} from 'lucide';
import {
  clearActiveAgentRun,
  loadActiveAgentRun,
  saveActiveAgentRun,
} from './active-run';
import { AgentPanel } from './agent';
import { getAutoFireBlockReason } from './auto-fire';
import { DiffView } from './diff';
import { preflightCode } from './preflight';
import { RecoveryView } from './recovery';
import { createReplAdapter, type ReplAdapter } from './repl';
import { getSnapshotLabel, SnapshotListView } from './snapshots';
import { SampleListView } from './samples';
import { SettingsPanel } from './settings';
import { RuntimeStateStore, type StagedAgentChange } from './state';
import { StatusView } from './status';
import './styles.css';

createIcons({
  icons: {
    AudioWaveform,
    History,
    OctagonAlert,
    Play,
    RefreshCcw,
    RotateCcw,
    Send,
    Settings,
    Square,
    Undo2,
    X,
  },
  attrs: {
    'aria-hidden': 'true',
    'stroke-width': 1.8,
  },
});

let repl: ReplAdapter | null = null;
let state: RuntimeStateStore | null = null;
let applyingRemoteCode = false;
let snapshotsCache: SnapshotRecord[] = [];
let activeAgentRun: ActiveAgentRun | null = null;
let startingAgentRun = false;
let agentRunUpdateQueue = Promise.resolve();
let agentRunPollTimer: number | null = null;

const EDITOR_UPDATE_DEBOUNCE_MS = 300;
const AGENT_RUN_STALE_POLL_MS = 1_500;

interface ActiveAgentRun {
  id: string;
  intent: string;
  editorVersion: EditorVersion;
  applyMode: ApplyMode;
  autoFireArmed: boolean;
  editorUpdateTimer: number | null;
  editorUpdateInFlight: boolean;
  editorUpdateTask: Promise<boolean> | null;
  pendingEditorVersion: EditorVersion | null;
}

const replElement = requireElement<HTMLElement>('#repl');
const evaluateButton = requireElement<HTMLButtonElement>('#evaluate');
const revertButton = requireElement<HTMLButtonElement>('#revert-last-good');
const stopButton = requireElement<HTMLButtonElement>('#stop');
const panicButton = requireElement<HTMLButtonElement>('#panic');
const statusElement = requireElement<HTMLElement>('#status');
const sampleListElement = requireElement<HTMLElement>('#sample-list');
const snapshotListElement = requireElement<HTMLElement>('#snapshot-list');
const snapshotDialog = requireElement<HTMLDialogElement>('#snapshots-dialog');
const openSnapshotsButton = requireElement<HTMLButtonElement>('#open-snapshots');
const closeSnapshotsButton = requireElement<HTMLButtonElement>('#close-snapshots');
const snapshotCountElement = requireElement<HTMLElement>('#snapshot-count');
const agentPanel = new AgentPanel(
  requireElement<HTMLFormElement>('#agent-form'),
  requireElement<HTMLTextAreaElement>('#agent-intent'),
  requireElement<HTMLInputElement>('#auto-fire'),
  requireElement<HTMLButtonElement>('#stage-change'),
  requireElement<HTMLButtonElement>('#cancel-change'),
  requireElement<HTMLButtonElement>('#undo-change'),
  requireElement<HTMLButtonElement>('#reset-agent-context'),
  requireElement<HTMLElement>('#agent-transcript'),
  requireElement<HTMLElement>('#agent-turn-history'),
  requireElement<HTMLElement>('#agent-current-turn'),
  requireElement<HTMLElement>('#agent-user-message'),
  requireElement<HTMLElement>('#agent-result'),
  requireElement<HTMLElement>('#agent-explanation'),
  requireElement<HTMLElement>('#agent-warnings'),
  requireElement<HTMLElement>('#agent-diff'),
  requireElement<HTMLDetailsElement>('#agent-activity'),
  requireElement<HTMLElement>('#agent-activity-summary'),
  requireElement<HTMLTimeElement>('#agent-activity-elapsed'),
  requireElement<HTMLOListElement>('#agent-activity-list'),
  requireElement<HTMLElement>('#agent-question'),
  requireElement<HTMLElement>('#agent-question-text'),
  requireElement<HTMLElement>('#agent-question-options'),
  requireElement<HTMLFormElement>('#agent-question-form'),
  requireElement<HTMLTextAreaElement>('#agent-question-answer'),
  requireElement<HTMLButtonElement>('#agent-question-submit'),
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
  requireElement<HTMLInputElement>('#settings-max-turns'),
  requireElement<HTMLInputElement>('#settings-max-elapsed'),
  requireElement<HTMLInputElement>('#settings-max-total-tokens'),
  requireElement<HTMLInputElement>('#settings-max-output-tokens'),
  requireElement<HTMLInputElement>('#settings-unlimited-total-tokens'),
  requireElement<HTMLButtonElement>('#reset-runtime-limits'),
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

function persistActiveAgentRun(): void {
  const activeRun = activeAgentRun;
  if (!activeRun) return;
  saveActiveAgentRun({
    id: activeRun.id,
    intent: activeRun.intent,
    editorVersion: activeRun.editorVersion,
    applyMode: activeRun.applyMode,
    autoFireArmed: activeRun.autoFireArmed,
  }, sessionStorage);
}

async function restoreActiveAgentRun(): Promise<void> {
  const stored = loadActiveAgentRun(sessionStorage);
  if (!stored) return;

  activeAgentRun = {
    ...stored,
    editorUpdateTimer: null,
    editorUpdateInFlight: false,
    editorUpdateTask: null,
    pendingEditorVersion: null,
  };
  agentPanel.showSubmission(stored.intent);
  try {
    enqueueAgentRunUpdate(await fetchAgentRun(stored.id));
  } catch {
    activeAgentRun = null;
    stopAgentRunPolling();
    clearActiveAgentRun(sessionStorage);
    status.set('Previous Agent Run is no longer available after reload.', 'warn');
  }
}

const status = new StatusView(statusElement);
const recovery = new RecoveryView(revertButton);
const sampleList = new SampleListView(sampleListElement);
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

async function evaluate(): Promise<boolean> {
  if (!repl || !state) {
    return false;
  }

  const code = repl.getCode();
  state.setEditorCode(code);
  const preflight = preflightCode(code);

  if (preflight.errors.length > 0) {
    status.set(preflight.errors.join(' '), 'error');
    return false;
  }

  try {
    await repl.evaluate();
    await saveTrack(code);
    const snapshot = await createSnapshot(code, getSnapshotLabel(code, state.get().changeSet));
    snapshotsCache = [snapshot, ...snapshotsCache.filter((item) => item.id !== snapshot.id)];
    renderSnapshots();
    repl.markClean();
    state.markEvaluated(code, snapshot);

    const warning = preflight.warnings[0];
    status.set(warning ? `Playing with warning: ${warning}` : `Playing ${new Date().toLocaleTimeString()}`, warning ? 'warn' : 'ok');
    return true;
  } catch (error) {
    status.set(error instanceof Error ? error.message : String(error), 'error');
    return false;
  }
}

async function stageAgentChange(value: { intent: string; applyMode: 'manual' | 'auto' }): Promise<void> {
  if (!repl || !state || activeAgentRun || startingAgentRun) return;
  startingAgentRun = true;
  agentPanel.setBusy(true);
  agentPanel.startActivity();
  status.set('Agent Run is starting...', 'warn');
  try {
    const editorVersion = await captureEditorVersion();
    const runtimeLimits = settingsPanel.getRuntimeLimits();
    const run = await startAgentRun(
      {
        intent: value.intent,
        editorVersion,
        applyMode: value.applyMode,
        ...(runtimeLimits ? { runtimeLimits } : {}),
      },
      settingsPanel.getConnection(),
    );
    activeAgentRun = {
      id: run.id,
      intent: value.intent,
      editorVersion,
      applyMode: value.applyMode,
      autoFireArmed: value.applyMode === 'auto',
      editorUpdateTimer: null,
      editorUpdateInFlight: false,
      editorUpdateTask: null,
      pendingEditorVersion: null,
    };
    agentPanel.acceptSubmission(value.intent);
    persistActiveAgentRun();
    scheduleActiveRunEditorUpdate();
    enqueueAgentRunUpdate(run);
    void refreshAgentRun(run.id);
  } catch (error) {
    activeAgentRun = null;
    stopAgentRunPolling();
    clearActiveAgentRun(sessionStorage);
    agentPanel.setBusy(false);
    agentPanel.clearActivity();
    status.set(error instanceof Error ? error.message : String(error), 'error');
  } finally {
    startingAgentRun = false;
  }
}

function enqueueAgentRunUpdate(run: AgentRunPublic): Promise<void> {
  agentRunUpdateQueue = agentRunUpdateQueue
    .then(() => applyAgentRunUpdate(run))
    .catch((error) => {
      if (activeAgentRun?.id === run.id) {
        activeAgentRun = null;
        stopAgentRunPolling();
        clearActiveAgentRun(sessionStorage);
        agentPanel.setBusy(false);
      }
      status.set(error instanceof Error ? error.message : String(error), 'error');
    });
  return agentRunUpdateQueue;
}

async function refreshAgentRun(runId: string): Promise<void> {
  try {
    await enqueueAgentRunUpdate(await fetchAgentRun(runId));
  } catch (error) {
    if (activeAgentRun?.id === runId) {
      status.set(error instanceof Error ? error.message : String(error), 'error');
    }
  }
}

function scheduleAgentRunPoll(runId: string): void {
  if (activeAgentRun?.id !== runId) return;
  stopAgentRunPolling();
  agentRunPollTimer = window.setTimeout(() => {
    agentRunPollTimer = null;
    void pollActiveAgentRun(runId);
  }, AGENT_RUN_STALE_POLL_MS);
}

function stopAgentRunPolling(): void {
  if (agentRunPollTimer === null) return;
  window.clearTimeout(agentRunPollTimer);
  agentRunPollTimer = null;
}

async function pollActiveAgentRun(runId: string): Promise<void> {
  if (activeAgentRun?.id !== runId) return;
  try {
    await enqueueAgentRunUpdate(await fetchAgentRun(runId));
  } catch {
    if (activeAgentRun?.id === runId) scheduleAgentRunPoll(runId);
  }
}

async function applyAgentRunUpdate(run: AgentRunPublic): Promise<void> {
  const activeRun = activeAgentRun;
  if (!activeRun || activeRun.id !== run.id) return;
  agentPanel.showActivity(run);

  if (run.status === 'running') {
    scheduleAgentRunPoll(run.id);
    agentPanel.clearQuestion();
    agentPanel.setBusy(true);
    status.set('Agent is working...', 'warn');
    return;
  }

  if (run.status === 'needs_input') {
    stopAgentRunPolling();
    agentPanel.setBusy(true);
    if (run.question) agentPanel.showQuestion(run.question);
    status.set('Agent needs a clarification before it can continue.', 'warn');
    return;
  }

  if (run.status === 'completed') {
    agentPanel.clearQuestion();
    if (await reconcileStaleCompletedRun(activeRun)) return;
    if (!(await stageCompletedAgentRun(activeRun, run))) {
      await reconcileStaleCompletedRun(activeRun);
      return;
    }
    finishAgentRun(run.id);
    return;
  }

  finishAgentRun(run.id);
  if (run.status === 'failed') {
    status.set(run.error?.message ?? 'Agent Run failed.', 'error');
  } else {
    status.set('Agent Run cancelled. Editor and playback were not changed.', 'warn');
  }
}

async function stageCompletedAgentRun(activeRun: ActiveAgentRun, run: AgentRunPublic): Promise<boolean> {
  if (run.finalResponse) {
    agentPanel.showResponse(run.finalResponse.content);
    diffView.clear();
    status.set('Agent response ready.', 'ok');
    return true;
  }
  if (!repl || !state || !run.finalChange) {
    throw new Error('Completed Agent Run did not provide a final result');
  }

  const finalChange = run.finalChange;
  if (finalChange.action === 'noop') {
    agentPanel.showNoop(finalChange);
    diffView.clear();
    status.set(finalChange.explanation, 'ok');
    return true;
  }

  const current = await captureEditorVersion();
  if (current.hash !== activeRun.editorVersion.hash) {
    return false;
  }

  const stagedChange: StagedAgentChange = {
    id: null,
    runId: run.id,
    intent: activeRun.intent,
    applyMode: activeRun.applyMode,
    preAgentCode: current.code,
    code: finalChange.code,
    explanation: finalChange.explanation,
    action: finalChange.action,
    warnings: finalChange.warnings,
  };

  try {
    applyingRemoteCode = true;
    repl.setCode(stagedChange.code);
  } finally {
    applyingRemoteCode = false;
  }
  state.stageChange(stagedChange);
  diffView.render(stagedChange.preAgentCode, stagedChange.code);
  agentPanel.showChange(stagedChange);
  agentPanel.setUndoAvailable(false);
  try {
    const stagedEditorVersion = await captureEditorVersion();
    const persistedChange = await acknowledgeAgentRunStage(run.id, {
      baseHash: activeRun.editorVersion.hash,
      editorVersion: stagedEditorVersion,
    });
    state.markStagedChangePersisted(run.id, persistedChange.id);
    await fireStagedChangeIfReady(activeRun, stagedChange, stagedEditorVersion);
  } catch (error) {
    status.set(
      `Agent change is staged, but its history could not be persisted: ${error instanceof Error ? error.message : String(error)}`,
      'error',
    );
  } finally {
    agentPanel.setUndoAvailable(state.get().changeSet?.runId === run.id);
  }
  return true;
}

async function reconcileStaleCompletedRun(activeRun: ActiveAgentRun): Promise<boolean> {
  const currentEditorVersion = await captureEditorVersion();
  const hasPendingUpdate = activeRun.editorUpdateInFlight || activeRun.pendingEditorVersion !== null;
  if (currentEditorVersion.hash === activeRun.editorVersion.hash && !hasPendingUpdate) {
    if (activeRun.editorUpdateTimer !== null) {
      window.clearTimeout(activeRun.editorUpdateTimer);
      activeRun.editorUpdateTimer = null;
    }
    return false;
  }

  if (activeRun.editorUpdateTimer !== null) {
    window.clearTimeout(activeRun.editorUpdateTimer);
    activeRun.editorUpdateTimer = null;
  }
  activeRun.pendingEditorVersion = currentEditorVersion;
  status.set('Agent is reconciling your latest editor changes...', 'warn');
  void flushActiveRunEditorUpdates(activeRun.id);
  return true;
}

async function fireStagedChangeIfReady(
  activeRun: ActiveAgentRun,
  stagedChange: StagedAgentChange,
  stagedEditorVersion: EditorVersion,
): Promise<void> {
  if (activeRun.applyMode !== 'auto') {
    status.set('Agent change staged. Review it, then Evaluate when ready.', 'warn');
    return;
  }

  const latestEditorVersion = await captureEditorVersion();
  const blockReason = getAutoFireBlockReason({
    armed: activeRun.autoFireArmed,
    editorMatchesStage: latestEditorVersion.hash === stagedEditorVersion.hash,
    code: stagedChange.code,
    warnings: stagedChange.warnings,
  });
  if (blockReason) {
    status.set(`Agent change staged. ${blockReason}`, 'warn');
    return;
  }

  if (await evaluate()) {
    status.set('Agent change is playing.', 'ok');
  }
}

function finishAgentRun(runId: string): void {
  if (activeAgentRun?.id !== runId) return;
  stopAgentRunPolling();
  if (activeAgentRun.editorUpdateTimer !== null) {
    window.clearTimeout(activeAgentRun.editorUpdateTimer);
  }
  activeAgentRun = null;
  clearActiveAgentRun(sessionStorage);
  agentPanel.clearQuestion();
  agentPanel.setBusy(false);
}

function scheduleActiveRunEditorUpdate(): void {
  const activeRun = activeAgentRun;
  if (!activeRun) return;
  if (activeRun.editorUpdateTimer !== null) {
    window.clearTimeout(activeRun.editorUpdateTimer);
  }
  activeRun.editorUpdateTimer = window.setTimeout(() => {
    activeRun.editorUpdateTimer = null;
    void queueActiveRunEditorVersion(activeRun.id);
  }, EDITOR_UPDATE_DEBOUNCE_MS);
}

async function queueActiveRunEditorVersion(runId: string): Promise<boolean> {
  const editorVersion = await captureEditorVersion();
  const activeRun = activeAgentRun;
  if (!activeRun || activeRun.id !== runId) return false;
  if (!activeRun.editorUpdateInFlight && editorVersion.hash === activeRun.editorVersion.hash) {
    activeRun.pendingEditorVersion = null;
    return true;
  }
  activeRun.pendingEditorVersion = editorVersion;
  return flushActiveRunEditorUpdates(activeRun.id);
}

async function flushActiveRunEditorUpdates(runId: string): Promise<boolean> {
  const activeRun = activeAgentRun;
  if (!activeRun || activeRun.id !== runId) return false;
  if (activeRun.editorUpdateInFlight) return activeRun.editorUpdateTask ?? false;
  const editorVersion = activeRun.pendingEditorVersion;
  if (!editorVersion) return true;
  if (editorVersion.hash === activeRun.editorVersion.hash) {
    activeRun.pendingEditorVersion = null;
    return true;
  }

  activeRun.pendingEditorVersion = null;
  activeRun.editorUpdateInFlight = true;
  const task = (async (): Promise<boolean> => {
    try {
      const run = await updateAgentRunEditor(activeRun.id, {
        baseHash: activeRun.editorVersion.hash,
        editorVersion,
      }, settingsPanel.getConnection());
      if (activeAgentRun?.id !== activeRun.id) return false;
      activeRun.editorVersion = editorVersion;
      persistActiveAgentRun();
      enqueueAgentRunUpdate(run);
      return true;
    } catch (error) {
      if (activeAgentRun?.id === activeRun.id) {
        status.set(
          `Agent Run could not receive the latest editor version: ${error instanceof Error ? error.message : String(error)}`,
          'warn',
        );
      }
      return false;
    } finally {
      if (activeAgentRun?.id === activeRun.id) {
        activeRun.editorUpdateInFlight = false;
        activeRun.editorUpdateTask = null;
        if (activeRun.pendingEditorVersion) {
          void flushActiveRunEditorUpdates(activeRun.id);
        }
      }
    }
  })();
  activeRun.editorUpdateTask = task;
  return task;
}

async function synchronizeActiveRunEditorVersion(runId: string): Promise<void> {
  const activeRun = activeAgentRun;
  if (!activeRun || activeRun.id !== runId) {
    throw new Error('Agent Run is no longer active');
  }
  if (activeRun.editorUpdateTimer !== null) {
    window.clearTimeout(activeRun.editorUpdateTimer);
    activeRun.editorUpdateTimer = null;
  }

  for (let attempt = 0; attempt < 4; attempt += 1) {
    if (!(await queueActiveRunEditorVersion(runId))) {
      throw new Error('Agent Run could not receive the latest editor version');
    }
    const currentRun = activeAgentRun;
    if (!currentRun || currentRun.id !== runId) {
      throw new Error('Agent Run is no longer active');
    }
    const currentEditorVersion = await captureEditorVersion();
    if (
      currentEditorVersion.hash === currentRun.editorVersion.hash
      && !currentRun.editorUpdateInFlight
      && currentRun.pendingEditorVersion === null
    ) {
      return;
    }
  }
  throw new Error('Editor kept changing before the Agent Run could continue');
}

async function captureEditorVersion(): Promise<EditorVersion> {
  const code = repl?.getCode() ?? '';
  const bytes = new TextEncoder().encode(code);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const hash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  return { code, hash };
}

async function undoAgentStage(): Promise<void> {
  const stagedChange = state?.get().changeSet;
  if (!repl || !state || !stagedChange) return;
  try {
    const code = stagedChange.id
      ? (await undoChange(stagedChange.id)).code
      : stagedChange.preAgentCode;
    applyingRemoteCode = true;
    repl.setCode(code);
    state.undoAgentChange(code);
    agentPanel.clearChange();
    diffView.clear();
    status.set('Agent change undone. Running music was not changed.', 'ok');
  } catch (error) {
    status.set(error instanceof Error ? error.message : String(error), 'error');
  } finally {
    applyingRemoteCode = false;
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

async function revertToSnapshot(snapshotId: string): Promise<boolean> {
  if (!repl || !state) {
    return false;
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
    return true;
  } catch (error) {
    applyingRemoteCode = false;
    status.set(error instanceof Error ? error.message : String(error), 'error');
    return false;
  }
}

function renderSnapshots(): void {
  snapshotCountElement.textContent = String(snapshotsCache.length);
  openSnapshotsButton.setAttribute('aria-label', `Open snapshots (${snapshotsCache.length})`);
  snapshotList.render(snapshotsCache, async (snapshotId) => {
    if (await revertToSnapshot(snapshotId)) snapshotDialog.close();
  });
}

async function stop(): Promise<void> {
  await repl?.stop();
  if (activeAgentRun) {
    activeAgentRun.autoFireArmed = false;
    persistActiveAgentRun();
  }
  agentPanel.disableAutoFire();
  status.set('Stopped', 'warn');
}

async function cancelActiveAgentRun(): Promise<void> {
  const activeRun = activeAgentRun;
  if (!activeRun) return;
  status.set('Cancelling Agent Run...', 'warn');
  try {
    enqueueAgentRunUpdate(await cancelAgentRun(activeRun.id));
  } catch (error) {
    status.set(error instanceof Error ? error.message : String(error), 'error');
  }
}

async function resetAgentContext(): Promise<void> {
  if (activeAgentRun || startingAgentRun) return;
  status.set('Resetting Agent context...', 'warn');
  try {
    await resetAgentConversation();
    agentPanel.resetConversationView();
    clearActiveAgentRun(sessionStorage);
    status.set('Agent conversation context reset.', 'ok');
  } catch (error) {
    status.set(error instanceof Error ? error.message : String(error), 'error');
  }
}

async function answerActiveAgentRun(value: { questionId: string; answer: string }): Promise<void> {
  const activeRun = activeAgentRun;
  if (!activeRun) return;
  agentPanel.setQuestionBusy(true);
  status.set('Continuing Agent Run...', 'warn');
  try {
    await synchronizeActiveRunEditorVersion(activeRun.id);
    const currentRun = activeAgentRun;
    if (!currentRun || currentRun.id !== activeRun.id) return;
    enqueueAgentRunUpdate(await answerAgentRun(
      currentRun.id,
      value,
      settingsPanel.getConnection(),
    ));
  } catch (error) {
    if (activeAgentRun?.id === activeRun.id) {
      agentPanel.setQuestionBusy(false);
    }
    status.set(error instanceof Error ? error.message : String(error), 'error');
  }
}

async function panic(): Promise<void> {
  await stop();
  status.set('Panic stop complete. Reload the page if visuals are stuck.', 'error');
}

async function boot(): Promise<void> {
  status.set('Waiting for REPL...', 'warn');
  agentPanel.setAutoFireAvailable(true);

  const settingsReady = settingsPanel.initialize().catch(() => {
    status.set('Agent settings unavailable. REPL controls remain available.', 'warn');
  });
  const samplesReady = fetchSamples().catch(() => null);
  const [serverState, snapshots, , sampleCatalog] = await Promise.all([
    fetchState(),
    fetchSnapshots(),
    settingsReady,
    samplesReady,
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
  if (sampleCatalog) {
    try {
      if (sampleCatalog.library.mapUrl) {
        await repl.registerSamples(sampleCatalog.library.mapUrl);
      }
      sampleList.render(sampleCatalog);
    } catch (error) {
      console.error('Could not register the local sample library.', error);
      sampleList.render(sampleCatalog, true);
      status.set('Local samples could not be loaded. Editor remains available.', 'warn');
    }
  } else {
    sampleList.renderUnavailable();
  }
  repl.onUpdate((code) => {
    if (!applyingRemoteCode) {
      state?.setEditorCode(code);
      scheduleActiveRunEditorUpdate();
      if (repl?.isDirty()) {
        status.set('Editor changed. Evaluate to save and play.', 'warn');
      }
    }
  });

  const track = await fetchTrack();
  applyTrack(track);
  await restoreActiveAgentRun();

  connectTrackEvents(
    (payload) => {
      applyTrack(payload);
    },
    () => {
      status.set('Event stream disconnected.', 'error');
    },
    (run) => {
      enqueueAgentRunUpdate(run);
    },
    () => {
      if (activeAgentRun) void refreshAgentRun(activeAgentRun.id);
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

openSnapshotsButton.addEventListener('click', () => {
  snapshotDialog.showModal();
});

closeSnapshotsButton.addEventListener('click', () => {
  snapshotDialog.close();
});

snapshotDialog.addEventListener('click', (event) => {
  if (event.target === snapshotDialog) snapshotDialog.close();
});

agentPanel.onSubmit((value) => { stageAgentChange(value); });
agentPanel.onUndo(() => { undoAgentStage(); });
agentPanel.onCancel(() => { cancelActiveAgentRun(); });
agentPanel.onResetContext(() => { resetAgentContext(); });
agentPanel.onAnswer((value) => { answerActiveAgentRun(value); });

boot().catch((error) => {
  status.set(error instanceof Error ? error.message : String(error), 'error');
});
