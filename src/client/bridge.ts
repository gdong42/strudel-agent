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

export interface DeclaredSample {
  name: string;
  tags: string[];
  description: string | null;
}

export interface SampleListPayload {
  configured: boolean;
  samples: DeclaredSample[];
}

export type ApplyMode = 'manual' | 'auto';
export type AgentRunStatus = 'running' | 'needs_input' | 'completed' | 'failed' | 'cancelled';

export interface EditorVersion {
  code: string;
  hash: string;
}

export interface AgentRuntimeLimits {
  maxTurns: number;
  maxElapsedSeconds: number;
  maxTotalTokens: number | null;
  maxOutputTokensPerTurn: number;
}

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

export type AgentActivityKind = 'model_turn' | 'commentary' | 'tool' | 'editor_update' | 'user_input';
export type AgentActivityStatus = 'running' | 'completed' | 'cancelled';
export type AgentActivityTool =
  | 'inspect_diff'
  | 'validate_candidate'
  | 'lookup_strudel_docs'
  | 'lookup_samples'
  | 'inspect_sample_usage'
  | 'finalize_change'
  | 'request_user_input'
  | 'agent_tool';

export interface AgentActivity {
  sequence: number;
  kind: AgentActivityKind;
  status: AgentActivityStatus;
  startedAt: number;
  completedAt: number | null;
  turn: number | null;
  tool: AgentActivityTool | null;
  message: string | null;
}

export interface AgentRunPublic {
  id: string;
  status: AgentRunStatus;
  question: AgentQuestion | null;
  finalChange: AgentFinalChange | null;
  error: AgentRunFailure | null;
  activities: AgentActivity[];
}

export interface AgentRunStartPayload {
  intent: string;
  editorVersion: EditorVersion;
  applyMode: ApplyMode;
  runtimeLimits?: AgentRuntimeLimits;
}

export interface AgentRunInputPayload {
  questionId: string;
  answer: string;
}

export interface AgentRunStagePayload {
  baseHash: string;
  editorVersion: EditorVersion;
}

export interface AgentRunEditorUpdatePayload {
  baseHash: string;
  editorVersion: EditorVersion;
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

export interface ProviderInfo {
  id: string;
  label: string;
  requiresApiKey: boolean;
  defaultModel: string | null;
  defaultRuntime: AgentRuntimeLimits;
}

export interface AgentSettingsPayload {
  defaultProvider: string;
  defaultModel: string | null;
  defaultRuntime: AgentRuntimeLimits;
  providers: ProviderInfo[];
}

export interface AgentConnection {
  provider: string | null;
  model: string | null;
  apiKey: string | null;
}

export function connectTrackEvents(
  onTrack: (payload: TrackPayload) => void,
  onError: () => void,
  onAgentRun?: (payload: AgentRunPublic) => void,
  onOpen?: () => void,
): EventSource {
  const source = new EventSource('/events');

  source.addEventListener('track', (event) => {
    onTrack(JSON.parse(event.data) as TrackPayload);
  });

  source.addEventListener('agent-run', (event) => {
    onAgentRun?.(JSON.parse(event.data) as AgentRunPublic);
  });

  source.addEventListener('error', () => {
    onError();
  });

  source.addEventListener('open', () => {
    onOpen?.();
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

export async function fetchSamples(): Promise<SampleListPayload> {
  const response = await fetch('/samples');
  if (!response.ok) {
    throw new Error(`Failed to load samples: ${response.status}`);
  }
  return response.json() as Promise<SampleListPayload>;
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

export async function startAgentRun(
  payload: AgentRunStartPayload,
  connection?: AgentConnection,
): Promise<AgentRunPublic> {
  const response = await fetch('/agent/runs', {
    method: 'POST',
    headers: agentHeaders(connection),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await responseError(response, `Failed to start Agent Run: ${response.status}`));
  }
  return response.json() as Promise<AgentRunPublic>;
}

export async function fetchAgentRun(runId: string): Promise<AgentRunPublic> {
  const response = await fetch(`/agent/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) {
    throw new Error(await responseError(response, `Failed to read Agent Run: ${response.status}`));
  }
  return response.json() as Promise<AgentRunPublic>;
}

export async function answerAgentRun(
  runId: string,
  payload: AgentRunInputPayload,
  connection?: AgentConnection,
): Promise<AgentRunPublic> {
  const response = await fetch(`/agent/runs/${encodeURIComponent(runId)}/input`, {
    method: 'POST',
    headers: agentHeaders(connection),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await responseError(response, `Failed to answer Agent Run: ${response.status}`));
  }
  return response.json() as Promise<AgentRunPublic>;
}

export async function cancelAgentRun(runId: string): Promise<AgentRunPublic> {
  const response = await fetch(`/agent/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' });
  if (!response.ok) {
    throw new Error(await responseError(response, `Failed to cancel Agent Run: ${response.status}`));
  }
  return response.json() as Promise<AgentRunPublic>;
}

export async function acknowledgeAgentRunStage(
  runId: string,
  payload: AgentRunStagePayload,
): Promise<ChangeRecord> {
  const response = await fetch(`/agent/runs/${encodeURIComponent(runId)}/stage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await responseError(response, `Failed to persist Agent Run stage: ${response.status}`));
  }
  return response.json() as Promise<ChangeRecord>;
}

export async function updateAgentRunEditor(
  runId: string,
  payload: AgentRunEditorUpdatePayload,
  connection?: AgentConnection,
): Promise<AgentRunPublic> {
  const response = await fetch(`/agent/runs/${encodeURIComponent(runId)}/editor`, {
    method: 'POST',
    headers: agentHeaders(connection),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await responseError(response, `Failed to update Agent Run editor: ${response.status}`));
  }
  return response.json() as Promise<AgentRunPublic>;
}

export async function fetchAgentSettings(): Promise<AgentSettingsPayload> {
  const response = await fetch('/agent/settings');
  if (!response.ok) throw new Error(`Failed to load agent settings: ${response.status}`);
  return response.json() as Promise<AgentSettingsPayload>;
}

export async function resetAgentConversation(): Promise<void> {
  const response = await fetch('/agent/conversation', { method: 'DELETE' });
  if (!response.ok) {
    throw new Error(await responseError(response, `Failed to reset Agent context: ${response.status}`));
  }
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

function agentHeaders(connection?: AgentConnection): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (connection?.provider) headers['X-Agent-Provider'] = connection.provider;
  if (connection?.model) headers['X-Agent-Model'] = connection.model;
  if (connection?.apiKey) headers['X-Agent-Api-Key'] = connection.apiKey;
  return headers;
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
