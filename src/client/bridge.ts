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

export interface ChangeWarning {
  level: 'info' | 'warn' | 'risk';
  message: string;
  category: 'sample' | 'visual' | 'structure' | 'performance' | 'mini-notation';
}

export interface ChangeRecord {
  id: string;
  projectId: string;
  sessionId: string;
  createdAt: number;
  intent: string;
  scope: string | null;
  intensity: string | null;
  applyMode: ApplyMode;
  preAgentCode: string;
  code: string;
  explanation: string;
  warnings: ChangeWarning[];
  undoneAt: number | null;
}

export interface ChangeRequestPayload {
  intent: string;
  currentCode: string;
  applyMode: ApplyMode;
  scope?: string;
  intensity?: string;
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

export async function createChange(payload: ChangeRequestPayload): Promise<ChangeRecord> {
  const response = await fetch('/changes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error((await response.text()) || `Failed to stage change: ${response.status}`);
  }
  return response.json() as Promise<ChangeRecord>;
}

export async function undoChange(changeId: string): Promise<{ change: ChangeRecord; code: string }> {
  const response = await fetch(`/changes/${encodeURIComponent(changeId)}/undo`, { method: 'POST' });
  if (!response.ok) {
    throw new Error((await response.text()) || `Failed to undo change: ${response.status}`);
  }
  return response.json() as Promise<{ change: ChangeRecord; code: string }>;
}
