export interface TrackPayload {
  projectId: string;
  sessionId: string;
  code: string;
  updatedAt: number;
}

export interface RuntimeStatePayload {
  projectId: string;
  sessionId: string;
  activeCode: string;
  editorCode: string;
  lastGoodCode: string;
}

export interface SnapshotRecord {
  id: string;
  projectId: string;
  sessionId: string;
  createdAt: number;
  label: string;
  code: string;
}

export interface SnapshotListPayload {
  snapshots: SnapshotRecord[];
}

export interface SnapshotRevertPayload {
  snapshot: SnapshotRecord;
  track: TrackPayload;
}

export type ApplyMode = 'manual' | 'auto';
export type AgentRunStatus = 'running' | 'needs_input' | 'completed' | 'failed' | 'cancelled';

export interface ChangeWarning {
  level: 'info' | 'warn' | 'risk';
  message: string;
  category: 'sample' | 'visual' | 'structure' | 'performance' | 'mini-notation';
}

export interface AgentQuestionOption {
  id: string;
  label: string;
  description: string | null;
}

export interface AgentQuestion {
  id: string;
  question: string;
  options: AgentQuestionOption[];
}

export interface AgentFinalChange {
  code: string;
  explanation: string;
  action: 'apply' | 'noop';
  warnings: ChangeWarning[];
}

export interface AgentRunFailure {
  code: 'budget_exhausted' | 'provider_error' | 'tool_error' | 'finalization_failed' | 'internal_error';
  message: string;
  retryable: boolean;
}

export interface AgentRunPublic {
  id: string;
  status: AgentRunStatus;
  question: AgentQuestion | null;
  finalChange: AgentFinalChange | null;
  error: AgentRunFailure | null;
}

export interface ChangeRecord {
  id: string;
  projectId: string;
  sessionId: string;
  createdAt: number;
  intent: string;
  applyMode: ApplyMode;
  preAgentCode: string;
  code: string;
  explanation: string;
  action: 'apply' | 'noop';
  provider: string;
  model: string | null;
  latencyMs: number | null;
  warnings: ChangeWarning[];
  undoneAt: number | null;
}

export interface ChangeRequestPayload {
  intent: string;
  currentCode: string;
  applyMode: ApplyMode;
  reconciliation?: ReconciliationPayload;
}

export interface ReconciliationPayload {
  baseCode: string;
  previousAgentCode: string;
  userEditDiff: string;
  attempt: number;
}

export interface ProviderInfo {
  id: string;
  label: string;
  requiresApiKey: boolean;
  defaultModel: string | null;
}

export interface AgentSettingsPayload {
  defaultProvider: string;
  defaultModel: string | null;
  providers: ProviderInfo[];
}

export interface AgentConnection {
  provider: string | null;
  model: string | null;
  apiKey: string | null;
}

export function connectTrackEvents(onTrack: (payload: TrackPayload) => void, onError: () => void): EventSource {
  const source = new EventSource('/events');

  source.addEventListener('track', (event) => {
    onTrack(JSON.parse(event.data) as TrackPayload);
  });

  source.addEventListener('error', () => {
    onError();
  });

  return source;
}

export async function fetchTrack(): Promise<TrackPayload> {
  const response = await fetch('/track');
  if (!response.ok) {
    throw new Error(`Failed to load track: ${response.status}`);
  }
  return response.json() as Promise<TrackPayload>;
}

export async function fetchState(): Promise<RuntimeStatePayload> {
  const response = await fetch('/state');
  if (!response.ok) {
    throw new Error(`Failed to load state: ${response.status}`);
  }
  return response.json() as Promise<RuntimeStatePayload>;
}

export async function saveTrack(code: string): Promise<void> {
  const response = await fetch('/track', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Failed to save track: ${response.status}`);
  }
}

export async function createSnapshot(code: string, label = 'Manual evaluate'): Promise<SnapshotRecord> {
  const response = await fetch('/snapshots', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, label }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Failed to create snapshot: ${response.status}`);
  }

  return response.json() as Promise<SnapshotRecord>;
}

export async function fetchSnapshots(): Promise<SnapshotListPayload> {
  const response = await fetch('/snapshots');
  if (!response.ok) {
    throw new Error(`Failed to load snapshots: ${response.status}`);
  }
  return response.json() as Promise<SnapshotListPayload>;
}

export async function revertSnapshot(snapshotId: string): Promise<SnapshotRevertPayload> {
  const response = await fetch(`/snapshots/${encodeURIComponent(snapshotId)}/revert`, {
    method: 'POST',
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Failed to revert snapshot: ${response.status}`);
  }

  return response.json() as Promise<SnapshotRevertPayload>;
}

export async function createChange(
  payload: ChangeRequestPayload,
  connection?: AgentConnection,
  signal?: AbortSignal,
): Promise<ChangeRecord> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (connection?.provider) headers['X-Agent-Provider'] = connection.provider;
  if (connection?.model) headers['X-Agent-Model'] = connection.model;
  if (connection?.apiKey) headers['X-Agent-Api-Key'] = connection.apiKey;
  const response = await fetch('/changes', {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    throw new Error(await responseError(response, `Failed to stage change: ${response.status}`));
  }
  return response.json() as Promise<ChangeRecord>;
}

export async function fetchAgentSettings(): Promise<AgentSettingsPayload> {
  const response = await fetch('/agent/settings');
  if (!response.ok) throw new Error(`Failed to load agent settings: ${response.status}`);
  return response.json() as Promise<AgentSettingsPayload>;
}

export async function testAgentProvider(connection: AgentConnection): Promise<{ ok: boolean; message: string }> {
  const response = await fetch('/agent/providers/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(connection),
  });
  if (!response.ok) throw new Error(await responseError(response, `Provider test failed: ${response.status}`));
  return response.json() as Promise<{ ok: boolean; message: string }>;
}

export async function undoChange(changeId: string): Promise<{ change: ChangeRecord; code: string }> {
  const response = await fetch(`/changes/${encodeURIComponent(changeId)}/undo`, { method: 'POST' });
  if (!response.ok) {
    throw new Error((await response.text()) || `Failed to undo change: ${response.status}`);
  }
  return response.json() as Promise<{ change: ChangeRecord; code: string }>;
}

async function responseError(response: Response, fallback: string): Promise<string> {
  const body = await response.text();
  if (!body) return fallback;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    return typeof parsed.detail === 'string' ? parsed.detail : fallback;
  } catch {
    return body;
  }
}
