import type { RuntimeStatePayload, SnapshotRecord, TrackPayload } from './bridge';

export interface ClientRuntimeState {
  projectId: string;
  sessionId: string;
  activeCode: string;
  editorCode: string;
  lastGoodCode: string;
  lastSnapshotId: string | null;
}

export type StateListener = (state: ClientRuntimeState) => void;

export class RuntimeStateStore {
  private state: ClientRuntimeState;
  private readonly listeners = new Set<StateListener>();

  constructor(initial: RuntimeStatePayload) {
    this.state = {
      ...initial,
      lastSnapshotId: null,
    };
  }

  get(): ClientRuntimeState {
    return this.state;
  }

  subscribe(listener: StateListener): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  setEditorCode(code: string): void {
    this.update({ editorCode: code });
  }

  loadTrack(payload: TrackPayload): void {
    this.update({
      projectId: payload.projectId,
      sessionId: payload.sessionId,
      editorCode: payload.code,
    });
  }

  markEvaluated(code: string, snapshot: SnapshotRecord | null): void {
    this.update({
      activeCode: code,
      editorCode: code,
      lastGoodCode: code,
      lastSnapshotId: snapshot?.id ?? this.state.lastSnapshotId,
    });
  }

  setLatestSnapshot(snapshot: SnapshotRecord): void {
    this.update({
      activeCode: snapshot.code,
      lastGoodCode: snapshot.code,
      lastSnapshotId: snapshot.id,
    });
  }

  markReverted(snapshot: SnapshotRecord): void {
    this.update({
      activeCode: snapshot.code,
      editorCode: snapshot.code,
      lastGoodCode: snapshot.code,
      lastSnapshotId: snapshot.id,
    });
  }

  canRevert(): boolean {
    return this.state.editorCode !== this.state.lastGoodCode;
  }

  private update(next: Partial<ClientRuntimeState>): void {
    this.state = { ...this.state, ...next };
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }
}
