import type { ApplyMode, EditorVersion } from './bridge';

export const ACTIVE_AGENT_RUN_KEY = 'strudel-agent.active-run.v1';

export interface StoredActiveAgentRun {
  id: string;
  intent: string;
  editorVersion: EditorVersion;
  applyMode: ApplyMode;
  autoFireArmed: boolean;
}

export function loadActiveAgentRun(storage: Storage): StoredActiveAgentRun | null {
  try {
    const raw = storage.getItem(ACTIVE_AGENT_RUN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return isStoredActiveAgentRun(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveActiveAgentRun(run: StoredActiveAgentRun, storage: Storage): void {
  try {
    storage.setItem(ACTIVE_AGENT_RUN_KEY, JSON.stringify(run));
  } catch {
    // Browser storage is an optional recovery aid.
  }
}

export function clearActiveAgentRun(storage: Storage): void {
  try {
    storage.removeItem(ACTIVE_AGENT_RUN_KEY);
  } catch {
    // Browser storage is an optional recovery aid.
  }
}

function isStoredActiveAgentRun(value: unknown): value is StoredActiveAgentRun {
  if (!value || typeof value !== 'object') return false;
  const run = value as Partial<StoredActiveAgentRun>;
  return (
    typeof run.id === 'string'
    && run.id.length > 0
    && typeof run.intent === 'string'
    && run.intent.length > 0
    && typeof run.editorVersion?.code === 'string'
    && typeof run.editorVersion?.hash === 'string'
    && run.editorVersion.hash.length > 0
    && (run.applyMode === 'manual' || run.applyMode === 'auto')
    && typeof run.autoFireArmed === 'boolean'
  );
}
